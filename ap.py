import subprocess
import os
from datetime import datetime

# Change directory to the Git repository
git_repo_path = r'C:\Users\User\Desktop\Git EEPROM4\eeprom-4'
try:
    os.chdir(git_repo_path)
except OSError as e:
    print("Error:", e)
    exit(1)

# Run git status command and capture the output
try:
    git_status_output = subprocess.check_output(['git', 'status'], stderr=subprocess.STDOUT)
    git_status_output = git_status_output.decode('utf-8')  # Decode bytes to string
except subprocess.CalledProcessError as e:
    git_status_output = e.output.decode('utf-8')

# Check if there are uncommitted changes
if 'nothing to commit' not in git_status_output.lower():
    log_message=("File version is not matching in Git.")
else:
    log_message=("File version is up to date in Git.")

timestamp = datetime.now()

# Write log message to file
log_file_path = 'log.txt'
with open(log_file_path, 'a') as log_file:
    log_file.write("[{}] {}\n".format(timestamp, log_message))

# Print log message
print(log_message)
