import pandas as pd

from flask import current_app

from application import db
from application.models.luma import LulcClass
from application.utils.common import AppMessageException, is_valid_hex_color, ErrorCodeEnum

from luma_ge.classification_scheme import LULC_Scheme_Manager

def get(known_session):
    return LulcClass.query.filter_by(session_id=known_session.id).all()

def process(known_session, classes, file, extension):
    if file:
        try:
            if extension == 'csv':
                df = pd.read_csv(file, usecols=range(3))
            elif extension == 'xlsx' or extension == 'xls':
                df = pd.read_excel(file, usecols=range(3))
        except Exception as e:
            current_app.logger.error('failed to read lulc classes file: {}'.format(str(e)))
            raise AppMessageException('failed to read file', error=ErrorCodeEnum.ERR_VALIDATION)

        df.columns = ['id', 'class', 'color']
        classes = df.to_dict('records')
    
    validate_classes(classes)
    delete(known_session)
    
    return iterate_classes(known_session, classes)
    

def validate_classes(classes):
    print(classes)
    if not classes:
        raise AppMessageException('please input: lulc classes list', error=ErrorCodeEnum.ERR_VALIDATION)

    if type(classes) != list:
        raise AppMessageException('invalid input: lulc classes, must be list', error=ErrorCodeEnum.ERR_VALIDATION)

    if len(classes) > 10000:
        raise AppMessageException('invalid input: lulc classes max 10000 classes', error=ErrorCodeEnum.ERR_VALIDATION)


def delete(known_session, commit=False):
    LulcClass.query.filter_by(session_id=known_session.id).delete()
    if commit:
        db.session.commit()


def iterate_classes(known_session, classes):
    all_classes = []
    all_classes_dict = []
    for cls in classes:
        class_id = cls.get('id')
        class_name = cls.get('class')
        class_color = cls.get('color')

        try:
            class_id = int(class_id)
        except ValueError:
            raise AppMessageException('invalid input: lulc classes, id must be integer', error=ErrorCodeEnum.ERR_VALIDATION)
        
        class_name = str(class_name)
        class_color = str(class_color)

        if not class_name:
            raise AppMessageException('invalid input: lulc classes, class name must not be empty', error=ErrorCodeEnum.ERR_VALIDATION)
        
        if not is_valid_hex_color(class_color):
            raise AppMessageException('invalid input: lulc classes, color must be valid hex color', error=ErrorCodeEnum.ERR_VALIDATION)
        
        known_class = LulcClass()
        known_class.session_id = known_session.id
        known_class.class_id = class_id
        known_class.class_name = class_name
        known_class.class_color = class_color
        all_classes.append(known_class)
        all_classes_dict.append(known_class.to_json())
    
    db.session.add_all(all_classes)
    db.session.commit()

    return all_classes_dict


def set_default_classes(known_session):
    delete(known_session)
    default_classes = LULC_Scheme_Manager.get_default_schemes()
    default_classes = default_classes[list(default_classes.keys())[0]]
    default_classes = [{
        'id': n.get('ID'),
        'class': n.get('Class Name'),
        'color': n.get('Color Code')
    } for n in default_classes]
    return iterate_classes(known_session, default_classes)