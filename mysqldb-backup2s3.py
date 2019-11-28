import boto3
import os

user_data_script = """#!/bin/bash 

{EXPORTS}

export S3_PATH={S3_PATH}
export REGION={REGION}
export AWS_ACCESS_KEY={AWS_ACCESS_KEY}
export AWS_ACCESS_KEY_ID={AWS_ACCESS_KEY_ID}
export AWS_SECRET_KEY={AWS_SECRET_KEY}
export AWS_SECRET_ACCESS_KEY={AWS_SECRET_ACCESS_KEY}
export AWS_SESSION_TOKEN={AWS_SESSION_TOKEN}
export AWS_SECURITY_TOKEN={AWS_SECURITY_TOKEN}

instanceid=$(curl http://169.254.169.254/latest/meta-data/instance-id) 
cd /tmp

# installing 
{INSTALLS}

# dumping db in s3
{BACKUPS}

# terminate instance
aws ec2 terminate-instances --instance-ids $instanceid --region $REGION 
"""

def get_private_ips(ec2, envs):
    private_ips = []
    for env in envs:
        response = ec2.describe_instances(
            Filters=[
                {
                    'Name': 'tag:environment',
                    'Values': [env]
                },
            ]
        )
        print("= Got it for", env, " - private IP:", response['Reservations'][0]['Instances'][0]['NetworkInterfaces'][0]['PrivateIpAddress'])
        private_ips.append(response['Reservations'][0]['Instances'][0]['NetworkInterfaces'][0]['PrivateIpAddress'])
    return ','.join(private_ips)

def extract_db_ips(ips, ports, users, passwords, envs):
    ips = ips.split(',')
    ports = ports.split(',')
    users = users.split(',')
    passwords = passwords.split(',')
    envs = envs.split(',')

    exports = ""
    backups = ""
    installs = "yum install -y mysql"

    for index, env in enumerate(envs):
        exports += "export DB_HOST_IP" + str(index) + "=" + ips[index] + "\n"
        exports += "export DB_HOST_PORT" + str(index) + "=" + ports[index] + "\n"

        if users[index] != '':
            users[index] = '"--user ' + users[index] + '"'
        if passwords[index] != '':
            passwords[index] = '"-p' + passwords[index] + '"'

        exports += "export DB_USER" + str(index) + "=" + users[index] + "\n"
        exports += "export DB_PASS" + str(index) + "=" + passwords[index] + "\n"

        path = "/tmp/db-backup-dump-" + env
        file_name = "db-backup-" + env + "-$(date +%d-%m-%Y_%H-%M).sql"
        backups += "mkdir -p " + path + "\n"

        backups += "mysqldump --host $DB_HOST_IP" + str(index) + " --port $DB_HOST_PORT" + str(index) + \
                    " $DB_USER{0} $DB_PASS{0}".format(str(index)) + " --all-databases > " + path + "/" + file_name + "\n"

        backups += "aws s3 cp " + path + "/db-backup-*.sql" + " $S3_PATH \n"
        backups += "aws s3 cp /var/log/cloud-init.log $S3_PATH/cloud-init-$(date +%d-%m-%Y_%H-%M)-{0}.log".format(env) + "\n"
        backups += "aws s3 cp /var/log/cloud-init-output.log $S3_PATH/cloud-init-output-$(date +%d-%m-%Y_%H-%M)-{0}.log".format(env) + "\n"

    return exports, installs, backups


def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name=os.environ['AWS_REGION'])
    if 'DB_HOST_IPs' not in os.environ:
        os.environ['DB_HOST_IPs'] = get_private_ips(ec2, os.environ['ENVs'].split(','))

    exports, installs, backups = extract_db_ips(os.environ['DB_HOST_IPs'], os.environ['DB_HOST_PORTs'], 
                                os.environ['DB_USERs'], os.environ['DB_PASSs'], os.environ['ENVs'])

    parameters = {
        'S3_PATH': os.environ['S3_PATH'] if 'S3_PATH' in os.environ else '',

        'AWS_ACCESS_KEY_ID': os.environ['AWS_ACCESS_KEY_ID'] if 'AWS_ACCESS_KEY_ID' in os.environ else '',
        'AWS_SECRET_ACCESS_KEY': os.environ['AWS_SECRET_ACCESS_KEY'] if 'AWS_SECRET_ACCESS_KEY' in os.environ else '',
        'AWS_ACCESS_KEY': os.environ['AWS_ACCESS_KEY'] if 'AWS_ACCESS_KEY' in os.environ else '',
        'AWS_SECRET_KEY': os.environ['AWS_SECRET_KEY'] if 'AWS_SECRET_KEY' in os.environ else '',
        'AWS_SESSION_TOKEN': os.environ['AWS_SESSION_TOKEN'] if 'AWS_SESSION_TOKEN' in os.environ else '',
        'AWS_SECURITY_TOKEN': os.environ['AWS_SECURITY_TOKEN'] if 'AWS_SECURITY_TOKEN' in os.environ else '',

        'REGION': os.environ['AWS_REGION'],

        'EXPORTS': exports,
        'BACKUPS': backups,
        'INSTALLS': installs,
    }
    user_data = user_data_script.format(**parameters)
    print(user_data)
    print("= Creating new instance...")
    new_instance = ec2.run_instances(
        ImageId='ami-b70554c8',
        MinCount=1,
        MaxCount=1,
        KeyName=os.environ['PRIVATE_EC2_KEY'],
        InstanceType='t2.micro',
        SecurityGroupIds=[os.environ['SECURITY_GROUP_ID']],
        SubnetId=os.environ['SUBNET_ID'],
        IamInstanceProfile={'Name': os.environ['IAM_INSTANCE_PROFILE']},
        UserData=user_data)
    print("= Done")
    return {
        'message': str(new_instance)
    }


if __name__ == "__main__":
    lambda_handler(None, None)
