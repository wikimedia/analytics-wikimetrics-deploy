from fabric.api import cd, env, put, require, shell_env, sudo, task, run
from functools import wraps
from string import Template

import os
import StringIO
import yaml

env.use_ssh_config = True
env.shell = '/bin/bash -c'

STAGES = {
    'staging': {
        'hosts': ['wikimetrics-staging.wikimetrics.eqiad.wmflabs'],
        'secrets_dir': 'secrets/private/staging',
        'source_branch': 'master',
        'deploy_branch': 'master',
        'debug': True,
    },
    'production': {
        'hosts': ['wikimetrics-01.wikimetrics.eqiad.wmflabs'],
        'secrets_dir': 'secrets/private/production',
        'source_branch': 'master',
        'deploy_branch': 'master',
        'debug': False,
    },
}

SOURCE_DIR = '/srv/wikimetrics/src'
CONFIG_DIR = '/srv/wikimetrics/config'
VENV_DIR = '/srv/wikimetrics/venv'
LOCAL_CONFIG_DIR = 'config_templates'

DB_CONFIG_FILE = 'db_config.yaml'
QUEUE_CONFIG_FILE = 'queue_config.yaml'
WEB_CONFIG_FILE = 'web_config.yaml'

DB_SECRETS_FILE = 'db_secrets.yaml'
WEB_SECRETS_FILE = 'web_secrets.yaml'


def sr(*cmd):
    """
    Sudo Run - Wraps a given command around sudo and runs it as the
    wikimetrics user
    """
    with shell_env(HOME='/srv/wikimetrics'):
        return sudo(' '.join(cmd), user='wikimetrics')


def set_stage(stage='staging'):
    """
    Sets the stage and populate the environment with the necessary
    config. Doing this allows accessing from anywhere stage related
    details by simply doing something like env.source_dir etc

    It also uses the values defined in the secrets directories
    to substitute the templatized config files for the db and web configs,
    and loads the final db, queue and web configs as strings into the
    environment
    """
    env.stage = stage
    for option, value in STAGES[env.stage].items():
        setattr(env, option, value)

    secrets_dir = STAGES[env.stage]['secrets_dir']

    # Load DB config into environment
    with open(secrets_dir + '/' + DB_SECRETS_FILE) as secrets, \
            open(LOCAL_CONFIG_DIR + '/' + DB_CONFIG_FILE) as config:
        db_config_template = Template(config.read())
        db_secrets = yaml.load(secrets)
        setattr(env, 'db_config', db_config_template.substitute(db_secrets))

    # Load Web config into environment
    with open(secrets_dir + '/' + WEB_SECRETS_FILE) as secrets, \
            open(LOCAL_CONFIG_DIR + '/' + WEB_CONFIG_FILE) as config:
        web_config_template = Template(config.read())
        web_secrets = yaml.load(secrets)
        setattr(env, 'web_config', web_config_template.substitute(web_secrets))

    # Load Queue config into environment
    with open(LOCAL_CONFIG_DIR + '/' + QUEUE_CONFIG_FILE) as config:
        setattr(env, 'queue_config', config.read())


def ensure_stage(fn):
    """
    Decorator to ensure the stage is set
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # The require operation will abort if the key stage
        # is not set in the environment
        require('stage', provided_by=(staging, production,))
        return fn(*args, **kwargs)
    return wrapper


@task
def production():
    set_stage('production')


@task
def staging():
    set_stage('staging')


@task
@ensure_stage
def initialize_server():
    """
    Setup an initial deployment on a fresh host.
    """
    print 'Setting up the ' + env.stage + ' server'
    # Sets up a virtualenv directory
    sr('mkdir', '-p', VENV_DIR)
    sr('virtualenv', '--python', 'python2', VENV_DIR)

    # Updates current version of wikimetrics-deploy
    update_deploy_repo()

    # Updates current version of wikimetrics source
    update_source_repo()

    # Uploads the db and oauth creds to the server
    upload_config()

    # Updates the virtualenv with new wikimetrics code
    upgrade_wikimetrics()

    # Initialize DB
    setup_db()

    # Update DB
    update_db()


@task
@ensure_stage
def deploy():
    """
    Deploys updated code to the web server
    """
    print 'Deploying to ' + env.stage

    # Updates current version of wikimetrics-deploy
    update_deploy_repo()

    # Updates current version of wikimetrics source
    update_source_repo()

    # Updates the virtualenv with new wikimetrics code
    upgrade_wikimetrics()

    # Uploads the db and oauth creds to the server
    upload_config()

    # Update DB
    update_db()

    # Restart wikimetrics queue, scheduler and web services
    restart_wikimetrics()


@ensure_stage
def update_source_repo():
    """
    Update the wikimetrics source repo
    """
    print 'Updating wikimetrics source repo'
    with cd(SOURCE_DIR):
        sr('git', 'fetch', 'origin', env.source_branch)
        sr('git', 'reset', '--hard', 'FETCH_HEAD')


@ensure_stage
def update_deploy_repo():
    """
    Updates the deployment repo
    """
    print 'Updating wikimetrics-deploy repo'
    with cd(CONFIG_DIR):
        sr('git', 'fetch', 'origin', env.deploy_branch)
        sr('git', 'reset', '--hard', 'FETCH_HEAD')


def upload_file(config, dest):
    """
    Converts config file contents from string to file buffer using StringIO
    and uploads to remote server
    """
    buffer = StringIO.StringIO()
    buffer.write(config)
    put(buffer, dest, use_sudo=True)
    buffer.close()


@ensure_stage
def upload_config():
    """
    Upload the queue, web and db configs to the remote host
    """
    print 'Uploading config files to remote host(s)'
    upload_file(env.web_config, CONFIG_DIR + '/' + WEB_CONFIG_FILE)
    upload_file(env.db_config, CONFIG_DIR + '/' + DB_CONFIG_FILE)
    upload_file(env.queue_config, CONFIG_DIR + '/' + QUEUE_CONFIG_FILE)


@ensure_stage
def upgrade_wikimetrics():
    """
    Installs upgraded versions of requirements (if applicable)
    """
    print 'Upgrading requirements'
    with cd(VENV_DIR):
        sr(VENV_DIR + '/bin/pip', 'install', '--upgrade', '-r',
            os.path.join(CONFIG_DIR, 'requirements.txt'))


@ensure_stage
def create_db_and_user(db_name, db_config):
    """
    Creates the database db_name and grants access to the
    user, as defined by the db_config, on the given remote mysql server
    """
    db_user = db_config['DB_USER_WIKIMETRICS']
    db_password = db_config['DB_PASSWORD_WIKIMETRICS']
    db_host = db_config['DB_HOST_WIKIMETRICS']
    # Because we are using labsdb on prod, this is a special case where we
    # cannot create database as the root user, and the wikimetrics user is
    # actually the same as the labsdb user - so we don't create it
    if env.stage == 'production':
        run("mysql -u {0} -p{1} -h {2} -e "
            .format(db_user, db_password, db_host) +
            "'CREATE DATABASE IF NOT EXISTS {0}'"
            .format(db_name))
    else:
        run("mysql -u root -h {0} -e ".format(db_host) +
            "'CREATE DATABASE IF NOT EXISTS {0}'".format(db_name))
        run("mysql -u root -h {0} -e ".format(db_host) +
            "'GRANT ALL ON `{0}`.* TO \"{1}\"@\"{2}\" identified by \"{3}\";'"
            .format(db_name, db_user, db_host, db_password))


@ensure_stage
def setup_db():
    """
    Creates the database and grants access to the wikimetrics user
    """
    print 'Setting up database and access'
    # Convert db config to yaml
    db_config = yaml.load(env.db_config)

    # Setup wikimetrics DB
    create_db_and_user(db_config['DB_NAME_WIKIMETRICS'], db_config)

    if env.debug:
        # Setup Testing DBs
        for db_name in db_config['DB_NAMES_TESTING']:
            create_db_and_user(db_name, db_config)


@ensure_stage
def update_db():
    """
    Creates and updates all tables by running migrations
    """
    print 'Bringing database uptodate by running migrations'
    with cd(SOURCE_DIR):
        run(VENV_DIR + '/bin/alembic upgrade head')


@task
@ensure_stage
def restart_wikimetrics():
    """
    Restarts the wikimetrics queue, scheduler and web server
    """
    print 'Restarting queue, scheduler and web server'
    sudo('service uwsgi-wikimetrics-web restart')
    sudo('service wikimetrics-queue restart')
    sudo('service wikimetrics-scheduler restart')
