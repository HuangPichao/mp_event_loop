import copy

from mp_event_loop.events import Event, CacheEvent
from mp_event_loop.event_loop import EventLoop
from mp_event_loop.mp_functions import mark_task_done, LoopQueueSize


__all__ = ['run_iter_event_loop', 'IterEventLoop']


def run_iter_event_loop(alive_event, event_queue, consumer_queue=None):
    """Run the event loop.

    Args:
        alive_event (multiprocessing.Event): Event to signal when to end the thread
        event_queue (multiprocessing.Queue/multiprocessing.JoinableQueue): Queue to get and run events with
        consumer_queue (multiprocessing.Queue/multiprocessing.JoinableQueue): Queue to pass results from the process
            to the thread.
    """
    iter_events = []
    # ===== Run the logging event loop =====
    for _ in LoopQueueSize(alive_event, event_queue):  # Iterate until a stop case then iterate the queue.qsize
        if len(iter_events) == 0 or not event_queue.empty():
            event = event_queue.get()

            if isinstance(event, Event):
                # Run the event
                event.exec_()
                if is_iterable(event.results):
                    event.iter = event.results
                    iter_events.append(event)

                elif event.has_output:
                    consumer_queue.put(event)

            mark_task_done(event_queue)

        # Loop through the iterators
        offset = 0
        for i in range(len(iter_events)):
            event = iter_events[i + offset]
            new_event = copy.copy(event)
            try:
                new_event.results = next(event.iter)
            except (TypeError, StopIteration):
                iter_events.pop(i)
                offset -= 1
                continue
            except Exception as err:
                new_event.error = err

            # Put the results on the queue
            if new_event.has_output:
                consumer_queue.put(new_event)

    alive_event.clear()


def is_iterable(obj):
    """Return if an object is iterable and not callable."""
    return not callable(obj) and (hasattr(obj, '__iter__') and not type(obj) == type)


class IterEventMixin(object):
    def exec_(self):
        """Get the command and run it"""
        # Get the command to run
        self.results = None
        self.error = None
        if is_iterable(self.target):
            # Save the iterable
            self.results = self.target
        elif callable(self.target):
            # Run the command
            try:
                self.results = self.run()
            except Exception as err:
                self.error = err
        else:
            self.error = ValueError("Invalid target (%s) given! Type %s" % (repr(self.target), str(type(self.target))))


class IterEvent(IterEventMixin, Event):
    pass


class IterCacheEvent(IterEventMixin, CacheEvent):
    pass


class IterEventLoop(EventLoop):
    run_event_loop = staticmethod(run_iter_event_loop)

    def add_event(self, target, *args, has_output=None, event_key=None, cache=False, re_register=False, **kwargs):
        """Add an event to be run in a separate process.

        Args:
            target (function/method/callable/Event): Event or callable to run in a separate process.
            *args (tuple): Arguments to pass into the target function.
            has_output (bool) [False]: If True save the results and put this event on the consumer/output queue.
            event_key (str)[None]: Key to identify the event or output result.
            cache (bool) [False]: If the target object should be cached.
            re_register (bool)[False]: Forcibly register this object in the other process.
            **kwargs (dict): Keyword arguments to pass into the target function.
            args (tuple)[None]: Keyword args argument.
            kwargs (dict)[None]: Keyword kwargs argument.
        """
        args = kwargs.pop('args', args)
        kwargs = kwargs.pop('kwargs', kwargs)

        if cache:
            return self.add_cache_event(target, *args, **kwargs, has_output=has_output, event_key=event_key,
                                        re_register=re_register)

        elif isinstance(target, Event):
            event = target

        else:
            if has_output is None:
                has_output = True
            event = IterEvent(target, *args, **kwargs, has_output=has_output, event_key=event_key)

        self.event_queue.put(event)

    def add_cache_event(self, target, *args, has_output=None, event_key=None, re_register=False, **kwargs):
        """Add an event that uses cached objects.

        Args:
            target (function/method/callable/Event): Event or callable to run in a separate process.
            *args (tuple): Arguments to pass into the target function.
            has_output (bool) [False]: If True save the results and put this event on the consumer/output queue.
            event_key (str)[None]: Key to identify the event or output result.
            re_register (bool)[False]: Forcibly register this object in the other process.
            **kwargs (dict): Keyword arguments to pass into the target function.
            args (tuple)[None]: Keyword args argument.
            kwargs (dict)[None]: Keyword kwargs argument.
        """
        args = kwargs.pop('args', args)
        kwargs = kwargs.pop('kwargs', kwargs)

        # Make sure cache is not a kwargs
        kwargs.pop('cache', None)

        if isinstance(target, CacheEvent):
            event = target
        elif isinstance(target, Event):
            args = args or target.args
            kwargs = kwargs or target.kwargs
            has_output = has_output or target.has_output
            event_key = event_key or target.event_key
            target = target.target

            if has_output is None:
                has_output = True
            event = IterCacheEvent(target, *args, **kwargs, has_output=has_output, event_key=event_key,
                                   re_register=re_register, cache=self.cache)
        else:
            if has_output is None:
                has_output = True
            event = IterCacheEvent(target, *args, **kwargs, has_output=has_output, event_key=event_key,
                                   re_register=re_register, cache=self.cache)

        self.event_queue.put(event)