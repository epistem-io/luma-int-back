import pandas as pd

from flask import current_app

from application import db
from application.models.luma import LulcClass
from application.utils.common import AppMessageException, is_valid_hex_color, ErrorCodeEnum

from luma_ge.classification_scheme import LULC_Scheme_Manager

def get(known_session):
    return LulcClass.query.filter_by(session_id=known_session.id).all()

# DEFAULT_CLASS_COLORS = [
#     '#EFC6D5', '#CC4778', '#99355A', '#F0F921', '#C0C71A',
#     '#909514', '#54570C', '#D7B1E4', '#650386', '#39024C'
# ]

DEFAULT_CLASS_COLORS = [
    "#EFC6D5", "#CC4778", "#FB7C54", "#FBC12D", "#A2A9F1",
    "#8E9231", "#00DF82", "#015F4D", "#043DCD", "#0372FF"
]

def process(known_session, classes, file, extension):
    if file:
        try:
            if extension == 'csv':
                df = pd.read_csv(file, usecols=range(2))
            elif extension == 'xlsx' or extension == 'xls':
                df = pd.read_excel(file, usecols=range(2))
        except Exception as e:
            current_app.logger.error('failed to read lulc classes file: {}'.format(str(e)))
            raise AppMessageException('Failed to read the file. Please ensure the file format is valid, all required columns are present, and the file contains data', error=ErrorCodeEnum.ERR_VALIDATION)

        df.columns = ['id', 'class']
        classes = df.to_dict('records')
        for i, cls in enumerate(classes):
            cls['color'] = DEFAULT_CLASS_COLORS[i % len(DEFAULT_CLASS_COLORS)]

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
        
        class_color = str(class_color)

        if not class_name:
            raise AppMessageException('invalid input: lulc classes, class name must not be empty', error=ErrorCodeEnum.ERR_VALIDATION)
        
        class_name = str(class_name)
        
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


def get_default_classes_list():
    default_classes = LULC_Scheme_Manager.get_default_schemes()
    default_classes = default_classes[list(default_classes.keys())[0]]
    return [{
        'id': n.get('ID'),
        'class': n.get('Class Name'),
        'color': n.get('Color Code')
    } for n in default_classes]


def remove_non_default(classes, commit=True):
    defaults = get_default_classes_list()
    expected = {(str(d['id']), str(d['class']).lower()) for d in defaults}
    kept = []
    removed = False
    for c in classes:
        if (str(c.class_id), str(c.class_name).lower()) in expected:
            kept.append(c)
        else:
            db.session.delete(c)
            removed = True
    if removed and commit:
        db.session.commit()
    return kept


def set_default_classes(known_session):
    delete(known_session)
    return iterate_classes(known_session, get_default_classes_list())


def ensure_valid_classes(known_session):
    classes = get(known_session)
    if not classes:
        return set_default_classes(known_session)
    if not remove_non_default(classes):
        return set_default_classes(known_session)
    return classes