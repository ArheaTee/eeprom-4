import NIDAQmx
import time

powerOnTime = float('nan')

def setPowerRelayState( state ):
    global powerOnTime
    
    daq = NIDAQmx.NIDAQmx()
    
 
    taskHandle = daq.CreateTask("")
    daq.CreateDOChan(taskHandle,'Dev1/port1/line0','',daq.CONST.DAQmx_Val_ChanPerLine)
    daq.StartTask(taskHandle)
    daq.WriteDigitalU8(taskHandle,1,False,1.0,daq.CONST.DAQmx_Val_GroupByChannel,[int(state)])
    daq.ClearTask(taskHandle)
    
    if state:
        if not powerOnTime > 0:
            powerOnTime = time.time()
    else:
       powerOnTime = float('nan')
    
def getPowerOnDuration():
    return time.time()-powerOnTime

if __name__ == "__main__":

   # setPowerRelayState(True)
    
    setPowerRelayState(False)