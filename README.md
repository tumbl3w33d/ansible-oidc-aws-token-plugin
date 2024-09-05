# ansible-oidc-aws-token-plugin

This is an ansible callback plugin which enriches the environment of a playbook run with variables used with ansible's AWS modules. That means you do not have to set them in any other way.

The AWS credentials used are temporary session tokens which can be retrieved from an AWS Cognito Identity Pool which is connected to an OIDC identity provider. This has only been tested with the one and only IDP – [kanidm](https://github.com/kanidm/kanidm). 🦀

It can probably be modified to work with others.

## ⚠️ Disclaimer

It is important to highlight that this plugin is provided on an 'as-is' basis, without any form of express or implied warranty. Under no circumstances shall the authors be held accountable for any damages or liabilities arising from the utilization of this plugin. Users are advised to proceed at their own risk.

## How to

* create a public client OAuth2 configuration in your IDP (i.e., no client_secret involved)
* create an **identity pool** in **AWS Cognito** that is linked to your IDP
  * during that you also create an **IAM identity provider** which is linked to your IDP as well
  * you will also be asked to assign a role to this **IAM identity provider** which is the one that will be assumed by this authentication process
    * this role has "**web identity**" configured as trusted entity
    * during creation, you point it to the **IAM identity provider** you just created
* you can apply further restrictions in your Cognito identity pool configuration and you should read about all of that to be sure you know what you are doing
* drop the plugin file into a path where ansible looks for plugins (by default that is `callback_plugins` in the project root, but you can configure others)
* enable the plugin in your `ansible.cfg` (`callbacks_enabled`)
* configure the plugin using environment variables
  * look for `os.environ.get` in the plugin code to know what you can configure

## What can I expect to happen?

You start the playbook and a browser window/tab appears with the configured URL of your IDP. Once you authenticated, you immediately get redirected to a local port that has been opened on `localhost`. This is the receiver of the `id_token`.

The plugin will then take this `id_token` to the AWS API which validates it with your IDP and, if succesful, returns temporary AWS credentials which are then set as environment variables in your playbook run.

## State of development

Probably has some rough edges but does the trick.
