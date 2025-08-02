# application/utils/__init__.py
from application.utils.cloud_storage import CloudStorage

from flask import render_template
from datetime import timedelta
from string import ascii_lowercase, digits
from sqlalchemy.orm.collections import InstrumentedList
from datetime import datetime, UTC
from werkzeug.utils import secure_filename

import requests
import ast
import math
import os
import uuid
import pathlib
import shutil
import zipfile

from .handler import *

gcs = CloudStorage()
upload_folder = 'uploaded-file'

def get_uuid():
    return str(uuid.uuid4())

def get_date():
    return datetime.now(UTC).replace(tzinfo=None)

def map_attr(data, map, nullify=[]):
    j = {}
    for n in map:
        if n in nullify: # jika ingin nullify user.password berarti input nullify user dan user.password
            continue
        s = []
        if '.' in n:
            s = n.split('.')
        if s:
            fmt = 'j{}'
            for d in range(len(s)):
                q = fmt.format(''.join(['''['{}']'''.format(s[x]) for x in range(d+1)]))
                vq = fmt.format(''.join(['''.get('{}')'''.format(s[x]) for x in range(d+1)]))
                if not eval(vq):
                    exec('{}{}'.format(q, ' = {}'))
                if d == len(s)-1:
                    exec('{}{}'.format(q, ' = {}'.format('data.{}'.format(n))))
        else:
            j[n] = eval('data.{}'.format(n))
            if type(j[n]) == InstrumentedList:
                j[n] = eval('[i.to_json() for i in data.{} if i.rowstatus==1] if data.{} else []'.format(n, n))
            elif type(j[n]) == datetime:
                j[n] = eval('(data.{}.isoformat() + ".000Z") if data.{} else None'.format(n, n))
    return j

def set_attr(attr):
    if not attr:
        return None
    a = ascii_lowercase + digits + '.,_'
    if all([n in a for n in set(attr)]):
        return [n.strip() for n in attr.split(',')]
    return None

def get_default_list_param(args):
    page_index = args.get('page_index')
    page_size = args.get('page_size')
    search_by = args.get('search_by') if args.get('search_by') else ''
    keywords = args.get('keywords') if args.get('keywords') else ''
    order_by_col = args.get('order_by_col') if args.get('order_by_col') else ''
    order_by_type = args.get('order_by_type') if args.get('order_by_type') else ''
    filter_by_col = args.get('filter_by_col') if args.get('filter_by_col') else ''
    filter_by_text = args.get('filter_by_text') if args.get('filter_by_text') else ''
    
    try:
        int(page_index)
    except:
        page_index = 1
    
    try:
        int(page_size)
    except:
        page_size = 10
    
    page_index = int(page_index)
    page_size = int(page_size)

    return {
        'page_index': page_index,
        'page_size': page_size,
        'search_by': search_by[:1000],
        'keywords': keywords[:1000],
        'order_by_col': order_by_col[:1000],
        'order_by_type': order_by_type[:1000],
        'filter_by_col': filter_by_col[:1000],
        'filter_by_text': filter_by_text[:1000],
    }

def allowed_file(filename, allowed_extensions):
    return filename != '' and '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions

def remove_tree_file(*paths):
    folder = pathlib.Path(*paths).resolve()
    if os.path.isdir(folder):
        shutil.rmtree(folder)

def save_uploaded_file(folder_name, file):
    filepath = os.path.join(upload_folder, folder_name)
    if not os.path.exists(filepath):
        os.makedirs(filepath)
    
    fullpath = os.path.join(filepath, secure_filename(file.filename))
    file.save(fullpath)

    gcs.upload(fullpath)
    
    return fullpath

def check_file(file, allowed_extensions):
    if not file:
        raise AppMessageException('No selected file')
    if not file.filename:
        raise AppMessageException('No selected file name')
    if not allowed_file(file.filename, allowed_extensions):
        raise AppMessageException('Invalid file format, only {} files are allowed'.format(', '.join([n.upper() for n in allowed_extensions])))
    
    return get_file_extension(file)

def get_file_extension(file):
    extension = file.filename.rsplit('.', 1)[1].lower()
    return extension

def process_zip(filepath, parent_folder, get_extension='shp'):
    extracted_filepath = os.path.join(upload_folder, parent_folder, 'temp_zip_extraction')
    os.makedirs(extracted_filepath, exist_ok=True)

    try:
        with zipfile.ZipFile(filepath, 'r') as zip_file:
            zip_file.extractall(extracted_filepath)

        # check if ada file shp didalem zip, return error if not
        filename = None
        for root, dirs, files in os.walk(extracted_filepath):
            for file in files:
                fullpath = os.path.join(root, file)
                if not file.startswith('.') and file.endswith(get_extension):
                    filename = fullpath
                gcs.upload(fullpath)
        if not filename:
            raise AppMessageException('No .{} file found in the ZIP file.'.format(get_extension))
        
        return filename
    except Exception as e:
        raise AppMessageException('Failed to process ZIP file')
        