#!/bin/bash
# Automated setup script for PulseAQI AWS Demo
set -e

echo "🚀 PulseAQI AWS Demo Setup"
echo "================================"

# Load environment variables if .env exists
if [ -f .env ]; then
    source .env
    echo "✓ Loaded configuration from .env"
fi

# Prompt for missing variables
read -p "AWS Region [${AWS_REGION:-us-east-1}]: " INPUT_REGION
AWS_REGION=${INPUT_REGION:-${AWS_REGION:-us-east-1}}

read -p "Database Name [${DATABASE_NAME:-pulseaqi_demo}]: " INPUT_DB
DATABASE_NAME=${INPUT_DB:-${DATABASE_NAME:-pulseaqi_demo}}

read -p "Table Name [${TABLE_NAME:-sensor_data}]: " INPUT_TABLE
TABLE_NAME=${INPUT_TABLE:-${TABLE_NAME:-sensor_data}}

read -p "EC2 Key Pair Name: " KEY_NAME
[ -z "$KEY_NAME" ] && echo "Error: Key pair name required" && exit 1

read -p "Your IP address (for SSH): " MY_IP
[ -z "$MY_IP" ] && echo "Error: IP address required" && exit 1

echo ""
echo "Configuration:"
echo "  Region: $AWS_REGION"
echo "  Database: $DATABASE_NAME"
echo "  Table: $TABLE_NAME"
echo "  Key Pair: $KEY_NAME"
echo "  SSH IP: $MY_IP"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
[[ ! $REPLY =~ ^[Yy]$ ]] && exit 1

# Create Timestream resources
echo ""
echo "📊 Creating Timestream database..."
aws timestream-write create-database \
  --database-name $DATABASE_NAME \
  --region $AWS_REGION || echo "Database may already exist"

echo "📊 Creating Timestream table..."
aws timestream-write create-table \
  --database-name $DATABASE_NAME \
  --table-name $TABLE_NAME \
  --retention-properties "MemoryStoreRetentionPeriodInHours=24,MagneticStoreRetentionPeriodInDays=7" \
  --region $AWS_REGION || echo "Table may already exist"

# Create IAM role
echo ""
echo "🔐 Creating IAM role..."
aws iam create-role \
  --role-name pulseaqi-ec2-role \
  --assume-role-policy-document file://ec2-trust-policy.json \
  2>/dev/null || echo "Role may already exist"

aws iam put-role-policy \
  --role-name pulseaqi-ec2-role \
  --policy-name timestream-write-policy \
  --policy-document file://timestream-write-policy.json

# Create instance profile
aws iam create-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile \
  2>/dev/null || echo "Instance profile may already exist"

aws iam add-role-to-instance-profile \
  --instance-profile-name pulseaqi-ec2-profile \
  --role-name pulseaqi-ec2-role \
  2>/dev/null || echo "Role already in profile"

echo "⏳ Waiting 10 seconds for IAM propagation..."
sleep 10

# Create security group and EC2
echo ""
echo "🖥️  Setting up EC2 instance..."

# Check if security group exists
SG_ID=$(aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=pulseaqi-mqtt-bridge" \
  --query "SecurityGroups[0].GroupId" \
  --output text \
  --region $AWS_REGION 2>/dev/null)

if [ "$SG_ID" == "None" ] || [ -z "$SG_ID" ]; then
    echo "Creating security group..."
    SG_ID=$(aws ec2 create-security-group \
      --group-name pulseaqi-mqtt-bridge \
      --description "Security group for PulseAQI MQTT bridge" \
      --region $AWS_REGION \
      --query 'GroupId' \
      --output text)
fi

echo "Security Group ID: $SG_ID"

# Allow SSH access
aws ec2 authorize-security-group-ingress \
  --group-id $SG_ID \
  --protocol tcp \
  --port 22 \
  --cidr ${MY_IP}/32 \
  --region $AWS_REGION \
  2>/dev/null || echo "SSH rule may already exist"

# Get latest Ubuntu 22.04 AMI
AMI_ID=$(aws ec2 describe-images \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
  --query "sort_by(Images, &CreationDate)[-1].ImageId" \
  --output text \
  --region $AWS_REGION)

echo "Using AMI: $AMI_ID"

# Launch EC2 instance
echo "Launching EC2 instance..."
INSTANCE_ID=$(aws ec2 run-instances \
  --image-id $AMI_ID \
  --count 1 \
  --instance-type t2.micro \
  --key-name $KEY_NAME \
  --security-group-ids $SG_ID \
  --iam-instance-profile Name=pulseaqi-ec2-profile \
  --user-data file://user-data.sh \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=pulseaqi-mqtt-bridge}]' \
  --region $AWS_REGION \
  --query 'Instances[0].InstanceId' \
  --output text)

echo "Instance ID: $INSTANCE_ID"

echo "⏳ Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids $INSTANCE_ID --region $AWS_REGION

PUBLIC_IP=$(aws ec2 describe-instances \
  --instance-ids $INSTANCE_ID \
  --query 'Reservations[0].Instances[0].PublicIpAddress' \
  --output text \
  --region $AWS_REGION)

echo ""
echo "✅ Setup Complete!"
echo "================================"
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo ""
echo "Next steps:"
echo "1. Wait 2-3 minutes for instance to finish bootstrapping"
echo "2. Upload Python script:"
echo "   scp -i $KEY_NAME.pem mqtt_bridge.py ubuntu@$PUBLIC_IP:/opt/pulseaqi/"
echo "3. SSH into instance:"
echo "   ssh -i $KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo "4. Start the service:"
echo "   sudo systemctl start pulseaqi-mqtt"
echo "5. Check logs:"
echo "   sudo journalctl -u pulseaqi-mqtt -f"
echo ""
echo "📊 Set up Grafana Cloud at: https://grafana.com"
echo ""
