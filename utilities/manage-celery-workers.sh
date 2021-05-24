#!/bin/sh

# Used for dev and dogfood, do not use in a production like environment.

start_worker() {
    # Start a worker for a given queue
    queue=$1
    echo "Starting worker for $queue"
    start-stop-daemon \
        --start --oknodo --quiet --background \
        --pidfile "/var/tmp/celeryd-$queue.pid" --make-pidfile \
        --startas "$PWD/bin/celery" -- worker \
        --queues="$queue"\
        --config=lp.services.job.celeryconfig \
        --hostname="$queue@%n" \
        --loglevel=DEBUG \
        --logfile="/var/tmp/celeryd-$queue.log"

}

stop_worker() {
    queue=$1
    echo "Stopping worker for $queue"
    start-stop-daemon --oknodo --stop --pidfile "/var/tmp/celeryd-$queue.pid"
}

case "$1" in
  start)
        for queue in launchpad_job launchpad_job_slow bzrsyncd_job bzrsyncd_job_slow branch_write_job branch_write_job_slow celerybeat
        do
            start_worker $queue
        done
        ;;
  stop)
        for queue in launchpad_job launchpad_job_slow bzrsyncd_job bzrsyncd_job_slow branch_write_job branch_write_job_slow celerybeat
        do
            stop_worker $queue
        done
        ;;

  restart|force-reload)
        for queue in launchpad_job launchpad_job_slow bzrsyncd_job bzrsyncd_job_slow branch_write_job branch_write_job_slow celerybeat
        do
            stop_worker $queue
        done
        sleep 1
        for queue in launchpad_job launchpad_job_slow bzrsyncd_job bzrsyncd_job_slow branch_write_job branch_write_job_slow celerybeat
        do
            start_worker $queue
        done
        echo "$NAME."
        ;;
  *)
        N=/etc/init.d/$NAME
        echo "Usage: $N {start|stop|restart|force-reload}" >&2
        exit 1
        ;;
esac
