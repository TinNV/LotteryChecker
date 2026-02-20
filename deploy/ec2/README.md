# AWS Deploy (EC2/Lightsail - Low Cost)

This deployment path is the smallest setup for now:
- One Linux VM (EC2 or Lightsail)
- Docker + Docker Compose
- Run `LotteryChecker` directly from this repo

It does not require ECR/App Runner/CloudFormation.

## 1. Create a small VM

Recommended for lowest ops:
- Lightsail Linux instance (smallest plan that fits your traffic)
- Or EC2 `t4g.small`/`t3.small` class (depends on your region and traffic)

Open inbound ports:
- `22` (SSH) from your IP only
- `80` (HTTP) from `0.0.0.0/0`

## 2. SSH into server

```bash
ssh -i <your-key>.pem ec2-user@<SERVER_PUBLIC_IP>
```

For Ubuntu AMI use `ubuntu` instead of `ec2-user`.

## 3. Install Docker

### Amazon Linux 2023

```bash
sudo dnf update -y
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
```

Install Docker Compose plugin:

```bash
mkdir -p ~/.docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/download/v2.39.1/docker-compose-linux-x86_64 -o ~/.docker/cli-plugins/docker-compose
chmod +x ~/.docker/cli-plugins/docker-compose
docker compose version
```

### Ubuntu 22.04

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
newgrp docker
docker compose version
```

## 4. First deploy

```bash
git clone <YOUR_REPO_URL> lottery-checker
cd lottery-checker
chmod +x deploy/ec2/deploy.sh deploy/ec2/update.sh
./deploy/ec2/deploy.sh
```

Open:

```text
http://<SERVER_PUBLIC_IP>/
```

## 5. Update later

```bash
cd ~/lottery-checker
./deploy/ec2/update.sh
```

## 6. Basic operations

```bash
cd ~/lottery-checker
docker compose -f deploy/ec2/docker-compose.yml logs -f
docker compose -f deploy/ec2/docker-compose.yml ps
docker compose -f deploy/ec2/docker-compose.yml restart
docker compose -f deploy/ec2/docker-compose.yml down
```

## 7. Notes

- App listens on container port `8080`, published to host port `80`.
- To use a different host port:

```bash
APP_PORT=8080 ./deploy/ec2/deploy.sh
```

then access `http://<SERVER_PUBLIC_IP>:8080/`.
