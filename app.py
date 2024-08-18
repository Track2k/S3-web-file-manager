import os
from flask import Flask, render_template, request, redirect, url_for, flash, send_file, Response
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
import io
from werkzeug.utils import secure_filename


load_dotenv()
app = Flask(__name__)
app.secret_key = os.urandom(24)  # For flash messages

s3 = boto3.client('s3',
                  aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                  aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                  region_name=os.getenv('AWS_REGION'))

BUCKET_NAME = os.getenv('AWS_BUCKET_NAME')

@app.route('/')
@app.route('/<path:prefix>')
def index(prefix=''):
    files, folders = list_files_and_folders(prefix)
    return render_template('index.html', files=files, folders=folders, current_prefix=prefix)


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'mov', 'avi', 'wmv'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

import mimetypes

@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.referrer or url_for('index'))
    
    file = request.files['file']
    prefix = request.form.get('prefix', '')
    
    if file.filename == '':
        flash('No selected file')
        return redirect(request.referrer or url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(prefix, filename).lstrip('/')
        
        # Determine the content type based on the file extension
        content_type, _ = mimetypes.guess_type(filename)
        if content_type is None:
            content_type = 'application/octet-stream'
        
        # Upload the file with the correct content type
        s3.upload_fileobj(
            file,
            BUCKET_NAME,
            file_path,
            ExtraArgs={'ContentType': content_type}
        )
        flash('File successfully uploaded')
    else:
        flash('File type not allowed. Please upload only images or videos.')
    
    return redirect(request.referrer or url_for('index'))

@app.route('/create_folder', methods=['POST'])
def create_folder():
    folder_name = request.form.get('folder_name')
    prefix = request.form.get('prefix', '')
    
    if not folder_name:
        flash('Folder name is required')
        return redirect(request.referrer or url_for('index'))
    
    folder_path = os.path.join(prefix, folder_name + '/', '').lstrip('/')
    s3.put_object(Bucket=BUCKET_NAME, Key=folder_path)
    
    return redirect(request.referrer or url_for('index'))

@app.route('/delete', methods=['POST'])
def delete():
    key = request.form.get('key')
    is_folder = request.form.get('is_folder') == 'true'
    
    if not key:
        flash('No item specified for deletion')
        return redirect(request.referrer or url_for('index'))
    
    try:
        if is_folder:
            delete_folder(key)
            
        else:
            s3.delete_object(Bucket=BUCKET_NAME, Key=key)
    except ClientError as e:
        flash(f'Error deleting item: {str(e)}')
    
    return redirect(request.referrer or url_for('index'))



@app.route('/view/<path:key>')
def view(key):
    try:
        file = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        content_type = file['ContentType']
        
        if 'text' in content_type:
            return file['Body'].read().decode('utf-8')
        else:
            return Response(
                file['Body'].read(),
                mimetype=content_type,
                headers={"Content-Disposition": "inline; filename={}".format(key.split('/')[-1])}
            )
    except ClientError as e:
        flash(f'Error viewing file: {str(e)}')
        return redirect(url_for('index'))

@app.route('/download/<path:key>')
def download(key):
    try:
        file = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        return send_file(
            io.BytesIO(file['Body'].read()),
            as_attachment=True,
            download_name=os.path.basename(key)
        )
    except ClientError as e:
        flash(f'Error downloading file: {str(e)}')
        return redirect(url_for('index'))

def delete_folder(prefix):
    paginator = s3.get_paginator('list_objects_v2')
    pages = paginator.paginate(Bucket=BUCKET_NAME, Prefix=prefix)
    delete_us = dict(Objects=[])
    for item in pages.search('Contents'):
        if item:
            delete_us['Objects'].append(dict(Key=item['Key']))
        
        # Delete once aws_s3 reaches maximum number of keys to delete
        if len(delete_us['Objects']) >= 1000:
            s3.delete_objects(Bucket=BUCKET_NAME, Delete=delete_us)
            delete_us = dict(Objects=[])
    # Delete remaining objects
    if len(delete_us['Objects']):
        s3.delete_objects(Bucket=BUCKET_NAME, Delete=delete_us)

def list_files_and_folders(prefix=''):
    response = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=prefix, Delimiter='/')
    files = []
    folders = []
    if 'Contents' in response:
        for item in response['Contents']:
            if not item['Key'].endswith('/'):  # It's a file
                files.append(item['Key'][len(prefix):])
    if 'CommonPrefixes' in response:
        for item in response['CommonPrefixes']:
            folders.append(item['Prefix'][len(prefix):].rstrip('/'))
    return files, folders

if __name__ == '__main__':
    app.run(debug=True)