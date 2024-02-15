import sys
import os.path
import os
from ctypes import *

def GetOperatorInput( title =  "", prompt = "", defaultInputValue =  ""):
    import subprocess
        
    return subprocess.check_output( [os.path.join( os.path.dirname(os.path.realpath(__file__)), "InputDialog.exe"), title, prompt, defaultInputValue], shell=False )

def InformationDialog( title = "", prompt = "" ):
    import subprocess
        
    return subprocess.check_output( [os.path.join( os.path.dirname(os.path.realpath(__file__)), "InputDialog.exe"), title, prompt], shell=False )

if __name__ == "__main__" :

    try:

        if len(sys.argv) >3:        
            GetOperatorInput( *sys.argv[1:] )
        else:           
            InformationDialog( *sys.argv[1:] )
            
            
    except Exception , ex:
        sys.stdout.write(repr(ex) + " " + repr(sys.exc_info()))