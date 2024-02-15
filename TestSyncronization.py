import threading
import time
import random
import sys
import traceback
from server.ProcessObjects import ProcessStatus

sharedStepResults = {}

class SyncObject(object):
    __syncObjects = {}
    __dictLock = threading.RLock()
    
    def __init__(self,testObj,timeout=300,running_only=True,serialize=False):
        with SyncObject.__dictLock:
            if not testObj.id in SyncObject.__syncObjects:
                SyncObject.__syncObjects[testObj.id] = self
                self._lockCount =  0
                self._lock         = threading.RLock()
                self._serializationLock = threading.RLock()
                self._event_1   = threading.Event()
                self._event_2   = threading.Event()
                self._executed =  False
        self.timeout = timeout
        self.running_only = running_only
        self.serialize = serialize
        self.testObj = testObj
        self.syncObj = SyncObject.__syncObjects[testObj.id]
                
    def __enter__(self):
        #print "Begin sync for %s [%s]" % (type(self).__name__ , threading.current_thread())
        print "000 SyncObject __enter__ Station:%d Test:%s Thread:%s" % (self.testObj.station_id, self.testObj._result.Name, threading.current_thread())
        syncObject = self.syncObj
        with syncObject._lock:
            syncObject._lockCount += 1    
            
        startTime = time.clock()
        while ( 1 ):
            with syncObject._lock:
                 if ( syncObject._lockCount == self.testObj.get_number_of_stations(self.running_only) ):        #running stations only
                    syncObject._event_2.clear()
                    syncObject._event_1.set()            
            #check every 500ms
            if syncObject._event_1.wait(0.5):
                break
            if ( (time.clock() - startTime) > self.timeout ):
                raise Exception("%s BeginSync timeout" % self.testObj._result.name)
                    
        with syncObject._lock:
            if self.serialize:
                syncObject._serializationLock.acquire()                    

            #print "Begin sync done for %s [%s]" % (self.testObj._result.Name , threading.current_thread())
            print "100 SyncObject __enter__ Station:%d Test:%s Thread:%s" % (self.testObj.station_id, self.testObj._result.Name, threading.current_thread())
            if ( syncObject._executed) :
                print "110 SyncObject __enter__ Station:%d Test:%s Thread:%s" % (self.testObj.station_id, self.testObj._result.Name, threading.current_thread())
                return False
            else:
                print "120 SyncObject __enter__ Station:%d Test:%s Thread:%s" % (self.testObj.station_id, self.testObj._result.Name, threading.current_thread())
                syncObject._executed = True
                return True
                
    def __exit__(self, type, value, tb):
        #print "End sync for [%s]" % (threading.current_thread())
        print "000 SyncObject __exit__ Station:%d Test:%s Thread:%s" % (self.testObj.station_id, self.testObj._result.Name, threading.current_thread())
        syncObject = self.syncObj
        if self.serialize:
            syncObject._serializationLock.release()
        with syncObject._lock:
            syncObject._lockCount -= 1    
            if ( syncObject._lockCount == 0 ):
                syncObject._event_1.clear()
                syncObject._event_2.set()
                syncObject._executed = False
                del SyncObject.__syncObjects[self.testObj.id]

        if not syncObject._event_2.wait(self.timeout):
            raise Exception("%s EndSync timeout" % self.testObj._result.Name)
        
def syncronize(run_func):
    def deco(self):
        timeout = getattr(self, "syncTimeout", 600)
        running_only = getattr(self, "syncRunningOnlyStations", True)
        serialize = getattr(self, "syncRunSerialized", False)
        runSingle = getattr(self, "syncRunSingle", False)     
        try:
            with SyncObject(self,timeout, running_only, serialize) as shouldRun:
                if shouldRun or not runSingle:
                    try:
                        result = run_func(self)
                    finally:
                        if runSingle:
                            sharedStepResults[self.id] = self._result
                    return result
                if not shouldRun and runSingle:
                    self._result.StatusResult = sharedStepResults[self.id].StatusResult
                    self._result.symptom_label = sharedStepResults[self.id].symptom_label
                    self._result.symptom_message = sharedStepResults[self.id].symptom_message
                    return sharedStepResults[self.id].StatusResult
        except:
            self._result.symptom_label = self.testObj._result.Name
            self._result.symptom_message = repr(traceback.format_exc())
            self._result.StatusResult = ProcessStatus.FAILED
            return ProcessStatus.FAILED
    return deco
  
def syncRunSingle(run_func):
    def deco(self):
        print "600 syncRunSingle.. "
        timeout = getattr(self, "syncTimeout", 600)
        running_only = getattr(self, "syncRunningOnlyStations", True)
        runSingle = getattr(self, "syncRunSingle", True) 
        try:
            with SyncObject(self, timeout, running_only) as shouldRun:        
                if shouldRun:
                    print "610 syncRunSingle Station:%d calling Run function" % (self.station_id)
                    try:
                        result = run_func(self)
                        print "620 syncRunSingle Station:%d returning Run function" % (self.station_id)
                        return result
                    except Exception, ex:
                        self._result.StatusResult = ProcessStatus.FAILED
                        self._result.symptom_label = "Exception"
                        self._result.symptom_message = repr(ex) + " " + repr(sys.exc_info()[0])
                        return ProcessStatus.FAILED
                    finally:
                        sharedStepResults[self.id] = self._result
            if not shouldRun:
                print "630 syncRunSingle Station:%d getting results" % (self.station_id)
                self._result.StatusResult = sharedStepResults[self.id].StatusResult
                self._result.symptom_label = sharedStepResults[self.id].symptom_label
                self._result.symptom_message = sharedStepResults[self.id].symptom_message
                print "640 syncRunSingle Station:%d returning getting results" % (self.station_id)
                return sharedStepResults[self.id].StatusResult		
        except:
            self._result.symptom_label = self.testObj._result.Name
            self._result.symptom_message = repr(traceback.format_exc())
            self._result.StatusResult = ProcessStatus.FAILED
            return ProcessStatus.FAILED
    return deco
  
def syncRunSerialized(run_func):
    def deco(self):
        timeout = getattr(self, "syncTimeout", 600)
        running_only = getattr(self, "syncRunningOnlyStations", True)        
        runSingle = getattr(self, "syncRunSingle", False)        
        try:
            with SyncObject(self,timeout, running_only, serialize=True) as shouldRun:
                if shouldRun or not runSingle:
                    try:
                        result = run_func(self)
                    finally:
                        if runSingle:
                            sharedStepResults[self.id] = self._result
                    return result
            if not shouldRun and runSingle:
                self._result.StatusResult = sharedStepResults[self.id].StatusResult
                self._result.symptom_label = sharedStepResults[self.id].symptom_label
                self._result.symptom_message = sharedStepResults[self.id].symptom_message
                return sharedStepResults[self.id].StatusResult
        except:
            self._result.symptom_label = self.testObj._result.Name
            self._result.symptom_message = repr(traceback.format_exc())
            self._result.StatusResult = ProcessStatus.FAILED
            return ProcessStatus.FAILED
    return deco

