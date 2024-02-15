# -*- coding: utf-8 -*-
import os
from subprocess import check_output

# โฟลเดอร์ของคุณที่ต้องการเช็ค
folder_path = 'C:\Users\User\Desktop\Git EEPROM4\eeprom-4'

# ฟังก์ชันเพื่อเช็คสถานะไฟล์ในโฟลเดอร์บนเครื่องคอม
def check_local_status(folder_path):
    local_files = {}
    for root, dirs, files in os.walk(folder_path):
        for file_name in files:
            file_path = os.path.join(root, file_name)
            # เช็คสถานะของไฟล์
            file_status = check_output(['git', 'status', '--porcelain', file_path])
            local_files[file_path] = file_status.strip()
    return local_files

# ฟังก์ชันเพื่อเช็คสถานะไฟล์ใน GitHub
def check_github_status(repo_url):
    github_files = {}
    # Clone โปรเจค GitHub ลงในโฟลเดอร์ชั่วคราว
    temp_folder = 'C:\Users\User\Desktop\Git EEPROM4\eeprom-4'
    check_output(['git', 'clone', repo_url, temp_folder])
    # ตรวจสอบสถานะไฟล์ในโฟลเดอร์ชั่วคราว
    github_files = check_local_status(temp_folder)
    # ลบโฟลเดอร์ชั่วคราว
    check_output(['rm', '-rf', temp_folder])
    return github_files

# เรียกใช้ฟังก์ชันเพื่อเช็คสถานะ
local_files = check_local_status(folder_path)
github_files = check_github_status('https://github.com/ArheaTee/eeprom-4.git')

# เปรียบเทียบสถานะไฟล์ระหว่างเครื่องคอมและ GitHub
for file_path, local_status in local_files.items():
    github_status = github_files.get(file_path)
    if github_status is None:
        print('{} ไม่มีใน GitHub'.format(file_path))
    elif local_status == github_status:
        print('{} อัพเดทแล้ว'.format(file_path))
    else:
        print('{} ต้องการการอัพเดท'.format(file_path))
