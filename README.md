Wikimetrics Deploy
===================

wikimetrics-deploy contains the fabric scripts and configuration info to help deploy [wikimetrics](https://github.com/wikimedia/analytics-wikimetrics).

## Configuration setup

The config folder contains templatized yaml configs for the wikimetrics web server, queue and db.

The secrets folder is set up with a private folder which is a git submodule that contains the production and staging secrets (db passwords, oauth creds) and clones only if you have access to it; and a public folder that contains a test folder as an example.

When initializing the server or deploying, fabric will substitute the config templates with the relevant secret keys and upload the final files to the destination config directory.

The STAGES global variable in the fabfile defines the staging and production enviroments, and the corresponding hosts and other config information.

The DB is setup locally for staging, and on wmf labsdb for production (so that we don't have to manage backups)

## How to deploy

```
# Clone the wikimetrics-deploy repo from gerrit

git clone ssh://madhuvishy@gerrit.wikimedia.org:29418/analytics/wikimetrics-deploy

# Look at the available fabric tasks
cd wikimetrics-deploy
wikimetrics-deploy [master] ⚡ fab -list
Available commands:

    deploy               Deploys updated code to the web server
    initialize_server    Setup an initial deployment on a fresh host.
    production
    restart_wikimetrics  Restarts the wikimetrics queue, scheduler and web server
    staging

# Initialize staging server - Do this only once
# (Probably never have to do this when deploying to an existing host)
fab staging initialize_server

# Or for production server
fab production initialize_server

# To deploy to staging
fab staging deploy

# Or to production
fab production deploy

# Example of initialize_server with only user specified output
# (You can see all of the debug output if you do not use the --hide and --show options)

wikimetrics-deploy [master] ⚡ fab staging initialize_server --hide everything --show user
Setting up the staging server
Updating wikimetrics-deploy repo
Updating wikimetrics source repo
Uploading config files to remote host(s)
Upgrading requirements
Setting up database and access
Bringing database uptodate

Done.
Disconnecting from madhuvishy@wikimetrics-staging.wikimetrics.eqiad.wmflabs... done.

# To restart wikimetrics
wikimetrics-deploy [master] ⚡ fab staging restart_wikimetrics
[wikimetrics-staging.wikimetrics.eqiad.wmflabs] Executing task 'restart_wikimetrics'
Restarting queue, scheduler and web server
[wikimetrics-staging.wikimetrics.eqiad.wmflabs] sudo: service uwsgi-wikimetrics-web restart
[wikimetrics-staging.wikimetrics.eqiad.wmflabs] sudo: service wikimetrics-queue restart
[wikimetrics-staging.wikimetrics.eqiad.wmflabs] sudo: service wikimetrics-scheduler restart

Done.
Disconnecting from madhuvishy@wikimetrics-staging.wikimetrics.eqiad.wmflabs... done.

```