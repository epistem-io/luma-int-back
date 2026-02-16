import pandas as pd

from application import db
from application.models.luma import LulcClass
from application.utils.common import AppMessageException, is_valid_hex_color


def process(known_session, classes, file, extension):
    if file:
        try:
            if extension == 'csv':
                df = pd.read_csv(file, usecols=range(3))
            elif extension == 'xlsx' or extension == 'xls':
                df = pd.read_excel(file, usecols=range(3))
        except Exception as e:
            raise AppMessageException('failed to read file')

        df.columns = ['id', 'class', 'color']
        classes = df.to_dict('records')
    
    validate_classes(classes)
    delete(known_session)
    iterate_classes(known_session, classes)
    

def validate_classes(classes):
    print(classes)
    if not classes:
        raise AppMessageException('please input: lulc classes list')

    if type(classes) != list:
        raise AppMessageException('invalid input: lulc classes, must be list')

    if len(classes) > 1000:
        raise AppMessageException('invalid input: lulc classes')


def delete(known_session, commit=False):
    LulcClass.query.filter_by(session_id=known_session.id).delete()
    if commit:
        db.session.commit()


def iterate_classes(known_session, classes):
    all_classes = []
    for cls in classes:
        class_id = cls.get('id')
        class_name = cls.get('class')
        class_color = cls.get('color')

        try:
            class_id = int(class_id)
        except ValueError:
            raise AppMessageException('invalid input: lulc classes, id must be integer')
        
        class_name = str(class_name)
        class_color = str(class_color)

        if not class_name:
            raise AppMessageException('invalid input: lulc classes, class name must not be empty')
        
        if not is_valid_hex_color(class_color):
            raise AppMessageException('invalid input: lulc classes, color must be valid hex color')
        
        known_class = LulcClass()
        known_class.session_id = known_session.id
        known_class.class_id = class_id
        known_class.class_name = class_name
        known_class.class_color = class_color
        all_classes.append(known_class)
    
    db.session.add_all(all_classes)
    db.session.commit()
