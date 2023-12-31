#!/usr/bin/env python
# -*- coding: latin1 -*-
#----------------------------------------------------------------------------
# glock.py:                 Global mutex
#
# See __doc__ string below.
#
# Requires:
#    - Python 1.5.2 or newer (www.python.org)
#    - On windows: win32 extensions installed
#           (http://www.python.org/windows/win32all/win32all.exe)
#    - OS: Unix, Windows.
#
# $Id: //depot/rgutils/rgutils/glock.py#5 $
#----------------------------------------------------------------------------
'''
This module defines the class GlobalLock that implements a global
(inter-process) mutex on Windows and Unix, using file-locking on
Unix.

@see: class L{GlobalLock} for more details.
'''

__version__ = '0.2.' + '$Revision: #5 $'[12:-2]
__author__ = 'Richard Gruet', 'rjgruet@yahoo.com'
__date__    = '$Date: 2005/06/19 $'[7:-2], '$Author: rgruet $'[9:-2]
__since__ = '2000-01-22'
__doc__ += '\n@author: %s (U{%s})\n@version: %s' % (__author__[0],
                                            __author__[1], __version__)
__all__ = ['GlobalLock', 'GlobalLockError', 'LockAlreadyAcquired', 'NotOwner']

import errno
import os
import re
import string
import sys

# System-dependent imports for locking implementation:
_windows = (sys.platform == 'win32')

if _windows:
    try:
        import pywintypes
        import win32api
        import win32event
    except ImportError:
        sys.stderr.write('The win32 extensions need to be installed!')
    try:
        import ctypes
    except ImportError:
        ctypes = None
else:   # assume Unix
    try:
        import fcntl
    except ImportError:
        sys.stderr.write("On what kind of OS am I ? (Mac?) I should be on "
                         "Unix but can't import fcntl.\n")
        raise
    import threading

# Exceptions :
# ----------
class GlobalLockError(Exception):
    ''' Error raised by the glock module.
    '''
    pass

class NotOwner(GlobalLockError):
    ''' Attempt to release somebody else's lock.
    '''
    pass

class LockAlreadyAcquired(GlobalLockError):
    ''' Non-blocking acquire but lock already seized.
    '''
    pass


#----------------------------------------------------------------------------
class GlobalLock:
#----------------------------------------------------------------------------
    ''' A global mutex.

        B{Specification}

         - The lock must act as a global mutex, ie block between different
           candidate processus, but ALSO between different candidate
           threads of the same process.

         - It must NOT block in case of reentrant lock request issued by
           the SAME thread.
         - Extraneous unlocks should be ideally harmless.

        B{Implementation}

        In Python there is no portable global lock AFAIK. There is only a
        LOCAL/ in-process Lock mechanism (threading.RLock), so we have to
        implement our own solution:

         - Unix: use fcntl.flock(). Recursive calls OK. Different process OK.
           But <> threads, same process don't block so we have to use an extra
           threading.RLock to fix that point.
         - Windows: We use WIN32 mutex from Python Win32 extensions. Can't use
           std module msvcrt.locking(), because global lock is OK, but
           blocks also for 2 calls from the same thread!
    '''
    RE_ERROR_MSG = re.compile (r"^\[Errno ([0-9]+)\]")

    def __init__(self, fpath, lockInitially=False, logger=None):
        ''' Creates (or opens) a global lock.

            @param fpath: Path of the file used as lock target. This is also
                          the global id of the lock. The file will be created
                          if non existent.
            @param lockInitially: if True locks initially.
            @param logger: an optional logger object.
        '''
        self.logger = logger
        self.fpath = fpath
        if os.path.exists(fpath):
            self.previous_lockfile_present = True
        else:
            self.previous_lockfile_present = False
        if _windows:
            self.name = string.replace(fpath, '\\', '_')
            self.mutex = win32event.CreateMutex(None, lockInitially, self.name)
        else: # Unix
            self.name = fpath
            self.flock = open(fpath, 'w')
            self.fdlock = self.flock.fileno()
            self.threadLock = threading.RLock()
        if lockInitially:
            self.acquire()

    def __del__(self):
        #print('__del__ called') ##
        try: self.release()
        except: pass
        if _windows:
            win32api.CloseHandle(self.mutex)
        else:
            try: self.flock.close()
            except: pass

    def __repr__(self):
        return '<Global lock @ %s>' % self.name

    def acquire(self, blocking=False):
        """ Locks. Attemps to acquire a lock.

            @param blocking: If True, suspends caller until done. Otherwise,
            LockAlreadyAcquired is raised if the lock cannot be acquired immediately.

            On windows an IOError is always raised after ~10 sec if the lock
            can't be acquired.
            @exception GlobalLockError: if lock can't be acquired (timeout)
            @exception LockAlreadyAcquired: someone already has the lock and
                       the caller decided not to block.
        """
        if self.logger:
            self.logger.info('Creating lockfile: %s', self.fpath)
        if _windows:
            if blocking:
                timeout = win32event.INFINITE
            else:
                timeout = 0
            r = win32event.WaitForSingleObject(self.mutex, timeout)
            if r == win32event.WAIT_FAILED:
                raise GlobalLockError("Can't acquire mutex: error")
            if not blocking and r == win32event.WAIT_TIMEOUT:
                raise LockAlreadyAcquired('Lock %s already acquired by '
                                          'someone else' % self.name)
        else:
            # First, acquire the global (inter-process) lock:
            if blocking:
                options = fcntl.LOCK_EX
            else:
                options = fcntl.LOCK_EX|fcntl.LOCK_NB
            try:
                fcntl.flock(self.fdlock, options)
            except IOError as message: #(errno 13: perm. denied,
                            #       36: Resource deadlock avoided)
                if not blocking and self._errnoOf (message) == errno.EWOULDBLOCK:
                    raise LockAlreadyAcquired('Lock %s already acquired by '
                                              'someone else' % self.name)
                else:
                    raise GlobalLockError('Cannot acquire lock on "file" '
                                          '%s: %s\n' % (self.name, message))
            #print('got file lock.') ##

            # Then acquire the local (inter-thread) lock:
            if not self.threadLock.acquire(blocking):
                fcntl.flock(self.fdlock, fcntl.LOCK_UN) # release global lock
                raise LockAlreadyAcquired('Lock %s already acquired by '
                                          'someone else' % self.name)
            if self.previous_lockfile_present and self.logger:
                self.logger.warning("Stale lockfile detected and claimed.")
            #print('got thread lock.') ##

        self.is_locked = True

    def release(self, skip_delete=False):
        ''' Unlocks. (caller must own the lock!)

            @param skip_delete: don't try to delete the file. This can
                be used when the original filename has changed; for
                instance, if the lockfile is erased out-of-band, or if
                the directory it contains has been renamed.

            @return: The lock count.
            @exception IOError: if file lock can't be released
            @exception NotOwner: Attempt to release somebody else's lock.
        '''
        if not self.is_locked:
            return
        if not skip_delete:
            if self.logger:
                self.logger.debug('Removing lock file: %s', self.fpath)
            os.unlink(self.fpath)
        elif self.logger:
            # At certain times the lockfile will have been removed or
            # moved away before we call release(); log a message because
            # this is unusual and could be an error.
            self.logger.debug('Oops, my lock file disappeared: %s', self.fpath)
        if _windows:
            if ctypes:
                result = ctypes.windll.kernel32.ReleaseMutex(self.mutex.handle)
                if not result:
                   raise NotOwner("Attempt to release somebody else's lock")
            else:
                try:
                    win32event.ReleaseMutex(self.mutex)
                    #print("released mutex")
                except pywintypes.error as e:
                    errCode, fctName, errMsg =  e.args
                    if errCode == 288:
                        raise NotOwner("Attempt to release somebody else's lock")
                    else:
                        raise GlobalLockError('%s: err#%d: %s' % (fctName, errCode,
                                                                  errMsg))
        else:
            # First release the local (inter-thread) lock:
            try:
                self.threadLock.release()
            except AssertionError:
                raise NotOwner("Attempt to release somebody else's lock")

            # Then release the global (inter-process) lock:
            try:
                fcntl.flock(self.fdlock, fcntl.LOCK_UN)
            except IOError: # (errno 13: permission denied)
                raise GlobalLockError('Unlock of file "%s" failed\n' %
                                                            self.name)
        self.is_locked = False

    def _errnoOf (self, message):
        match = self.RE_ERROR_MSG.search(str(message))
        if match:
            return int(match.group(1))
        else:
            raise Exception ('Malformed error message "%s"' % message)

#----------------------------------------------------------------------------
def test():
#----------------------------------------------------------------------------
    ##TODO: a more serious test with distinct processes !

    print('Testing glock.py...')

    # unfortunately can't test inter-process lock here!
    lockName = 'myFirstLock'
    l = GlobalLock(lockName)
    if not _windows:
        assert os.path.exists(lockName)
    l.acquire()
    l.acquire() # reentrant lock, must not block
    l.release()
    l.release()

    try: l.release()
    except NotOwner: pass
    else: raise Exception('should have raised a NotOwner exception')

    # Check that <> threads of same process do block:
    import threading
    import time
    thread = threading.Thread(target=threadMain, args=(l,))
    print('main: locking...', end='')
    l.acquire()
    print(' done.')
    thread.start()
    time.sleep(3)
    print('\nmain: unlocking...', end='')
    l.release()
    print(' done.')
    time.sleep(0.1)

    print('=> Test of glock.py passed.')
    return l

def threadMain(lock):
    print('thread started(%s).' % lock)
    try: lock.acquire(blocking=False)
    except LockAlreadyAcquired: pass
    else: raise Exception('should have raised LockAlreadyAcquired')
    print('thread: locking (should stay blocked for ~ 3 sec)...', end='')
    lock.acquire()
    print('thread: locking done.')
    print('thread: unlocking...', end='')
    lock.release()
    print(' done.')
    print('thread ended.')

#----------------------------------------------------------------------------
#       M A I N
#----------------------------------------------------------------------------
if __name__ == "__main__":
    l = test()
