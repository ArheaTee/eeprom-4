import sys
import os.path
import os
from ctypes import *

def GetOperatorInput( title, prompt ):
    import subprocess
        
    return subprocess.check_output( [os.path.join( os.path.dirname(os.path.realpath(__file__)), "InputDialog.exe"), title, prompt], shell=False )

def InformationDialog( title, prompt ):
    user32 = windll.user32
    OK_Cancel = c_ulong(1)
    
    result = user32.MessageBoxA( None, title, prompt, OK_Cancel )
    if result == 1:
        return "OK"
    else:
        return "Cancel"
    

if __name__ == "__main__" :

    try:

        if len(sys.argv) > 2:        
            text = ""
            title = sys.argv[1]
            prompt = sys.argv[2]

            GetOperatorInput( title, prompt )
            
            
    except Exception , ex:
        sys.stdout.write(repr(ex) + " " + repr(sys.exc_info()))