import requests
import sys
import time
import os
import json
from ftplib import FTP_TLS
from downloader import PyFTPclient

url = '' # url of the seedbox, imported from settings.json and set in import_settings
max_retry = 10 # the max number of times we accept a failed request before stopping
auth_header = {} # auth header set by the login_request to be used by other requests
settings_file_path = 'settings.json' #path to the settings json file used in import_settings

# There are two settings dicts that are set up in import_settings and used throughout:
    # data contains: 
        # login_requests a dict containing username and password for use on the seedbox web page
        # download_details a dict containing:
        #   destination (the destination the file will be installed to on the server),
        #   isBasePath (bool for is the file in the base path of the server),
        #   start (bool for if the download should start),
        #   tags (list of string tags applied to the download)
    # ftp_data contains:
        # host
        # port
        # username
        # password


def download():
    global max_retry

    try:
        settings = import_settings()
    except:
        print("Failed to import settings from settings.json")
        return

    data = settings["data"]
    ftp_data = settings["ftp_data"]
    login_response = None
    download_response = None
    file_hash = extract_hash()
    
    if file_hash is None:
        return

    #make the login_request to get the jwt token and set it
    login_response = login_request(data["login_details"])
    while login_response is None:
        if max_retry == 0:
            return
        max_retry -= 1
        login_response = login_request(data["login_details"])

    #make the download request
    download_response = download_request(data["download_details"])
    while download_response is None:
        if max_retry == 0:
            return
        max_retry -= 1
        download_response = download_request(data["download_details"])

    #set the largest_byte_size and file_name
    #returns a dict containg file_name and file_total_size
    info_response = find_largest_file_name_and_size(file_hash)
    if info_response is None:
        return
    
    #check the download status until the file is downloaded to seedbox
    download_status_resposne = check_seedbox_download_status(info_response["file_name"], info_response["file_total_size"], file_hash)
    if download_status_resposne is None:
        return

    start_ftp_download(ftp_data, info_response["file_name"], file_hash)

def import_settings():
    global url
    with open(settings_file_path) as f:
        data = json.load(f)
    url = data["url"]
    ftp_host_ip_address = data["ftp_host_ip_address"]
    ftp_port = int(data["ftp_port"])
    ftp_username = data["ftp_username"]
    ftp_password = data["ftp_password"]
    ftp_data = {"host" : ftp_host_ip_address, "port" : ftp_port, "username" : ftp_username, "password" : ftp_password}
    login_details = data["login_details"]
    download_details = data["download_details"]
    download_details["urls"] = [sys.argv[1]]
    return {"data" : data, "ftp_data" : ftp_data}

def login_request(login_details):
    global auth_header
    login_request = requests.post(url + '/auth/authenticate', data = login_details)
    if login_request.status_code != 200:
        print('Login Failed: Check username and password')
        return None
    jwt = login_request.json()["token"].split('JWT ')[1]
    jwt = 'jwt='+jwt
    auth_header = {'Cookie' : jwt}
    return 1

def extract_hash():
    try:
        return sys.argv[1].split(':btih:')[1].split('&')[0].upper()
    except:
        print('Magnet link not in a valid form')
        return None

def download_request(download_details):
    download_request = requests.post(url + '/api/client/add', headers = auth_header, json = download_details)
    if download_request.status_code != 200:
        print('Download request failed, seedbox may be having issues')
        return None
    return 1

def find_largest_file_name_and_size(file_hash):
    file_name = ''
    file_total_size = 0
    global max_retry
    largest_byte_size = 0
    while file_name == '':
        time.sleep(5)
        find_name_request = requests.post(url + '/api/client/torrent-details', headers = auth_header, data = {'hash' : file_hash})
        if find_name_request.status_code != 200:
            print('Unable to find name, most likely a network issue')
            if max_retry == 0:
                return None
            else:
                max_retry -= 1
                continue
        files = find_name_request.json()["fileTree"]["files"]
        for entry in files:
            if str(entry['filename']).find('.meta') != -1:
                break
            if int(entry["sizeBytes"]) > largest_byte_size:
                largest_byte_size = int(entry['sizeBytes'])
                file_name = str(entry['filename'])
            file_total_size += int(entry['sizeBytes'])
    return {"file_name" : file_name, "file_total_size" : file_total_size}

def check_seedbox_download_status(file_name, file_total_size, file_hash):
    global max_retry
    file_downloaded = False
    downloaded = 0
    while file_downloaded == False:
        time.sleep(5)
        check_download_request = requests.post(url + '/api/client/torrent-details', headers = auth_header, data = {'hash' : file_hash})
        if check_download_request.status_code != 200:
            print('Unable to check download status, the hash extracted may be wrong or the file may be deleted from the seedbox')
            if max_retry == 0:
                return None
            else:
                max_retry -= 1
                continue
        files = check_download_request.json()["fileTree"]["files"]
        file_downloaded = True
        downloaded = 0
        for entry in files:
            if entry["percentComplete"] != "100":
                file_downloaded = False
            downloaded += int(entry["sizeBytes"])*(int(entry['percentComplete'])/100)
        os.system('clear')
        print(str(int(downloaded / file_total_size * 100)) + '%')
    return 1

def start_ftp_download(ftp_data, file_name, file_hash):
    directory_name = None
    http_download_request = requests.head(url + '/api/download?hash=' + file_hash, headers = auth_header)
    if http_download_request.status_code != 200:
        print('File is not within a directory. Looking in root')

    if 'Content-Disposition' in http_download_request.headers:
        directory_name = http_download_request.headers['Content-Disposition'].split('filename="')[1].split('.tar')[0]
        print('File is in directory: ' + directory_name)
    obj = PyFTPclient(host=ftp_data["host"], port=ftp_data["port"], login=ftp_data["username"], passwd=ftp_data["password"], directory = directory_name)
    print('Starting FTP Download:')
    obj.DownloadFile(file_name, '/hdd/share/Movies/' + file_name)

if __name__ == "__main__":
    download()
