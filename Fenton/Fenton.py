#!/usr/bin/python

import os
import sys
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler

def PrintPaths(message="Current Path:"):
    print message
    for entry in sys.path:
        print entry
    print "\n\n"


PrintPaths('sys.path at startup:')

project_root = os.getcwd()
print "Project Folder Set to [" + project_root + "]"
sys.path.append(project_root)

opentest_path = os.path.abspath(os.path.join(project_root ,'..\\..\\OpenTest'))
print "OpenTest Folder Set to [" + opentest_path + "]"
sys.path.append(opentest_path)

instruments_path = os.path.abspath(os.path.join(project_root ,'..\\Instruments'))
print "Instruments Folder Set to [" + instruments_path + "]"
sys.path.append(instruments_path)

cth_modules_path = os.path.abspath(os.path.join(project_root ,'..\\CthModules'))
print "CTH Modules Folder Set to [" + cth_modules_path + "]"
sys.path.append(cth_modules_path)

server_executable = os.path.abspath(os.path.join(".","..\\..\\OpenTest", "server"))
server_executable = os.path.join(server_executable,"server.py")
print "Executing [" + server_executable + "]"

PrintPaths('sys.path after additions')

test_exec_cfg_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'testexec.cfg')
print 'testexec.cfg path: %s' % test_exec_cfg_path

sys.argv = ['server.py',test_exec_cfg_path]

os.chdir('\\')

execfile(server_executable)
