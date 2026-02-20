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
- `443` (HTTPS) from `0.0.0.0/0`

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
cp .env.example .env
# edit .env for your environment (ADMIN_PASSWORD, DYNAMODB_SEARCH_TABLE, etc.)
chmod +x deploy/ec2/deploy.sh deploy/ec2/update.sh
./deploy/ec2/deploy.sh
```

If script execute permission is missing, run via bash directly:

```bash
bash deploy/ec2/deploy.sh
```

Open:

```text
http://<SERVER_PUBLIC_IP>/
```

### 4.1 Copy local `.env` to EC2 (optional)

Use this when `.env` is kept only on your local machine and is not committed to Git.

From local Windows PowerShell:

```powershell
cd C:\WIP\AI\LotteryChecker
.\deploy\ec2\copy-env-to-ec2.ps1 -HostName <SERVER_PUBLIC_DNS_OR_IP> -KeyFile .\deploy\ec2\<your-key>.pem
```

If PowerShell execution policy blocks script execution:

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\ec2\copy-env-to-ec2.ps1 -HostName <SERVER_PUBLIC_DNS_OR_IP> -KeyFile .\deploy\ec2\<your-key>.pem
```

From local Linux/macOS shell:

```bash
cd /path/to/lottery-checker
chmod +x deploy/ec2/copy-env-to-ec2.sh
./deploy/ec2/copy-env-to-ec2.sh --host <SERVER_PUBLIC_DNS_OR_IP> --key ./deploy/ec2/<your-key>.pem
```

Optional flags:
- PowerShell: `-RemoteUser`, `-RemoteDir`, `-LocalEnvFile`, `-Port`
- Bash: `--user`, `--remote-dir`, `--env-file`, `--port`

## 5. Update later

```bash
cd ~/lottery-checker
./deploy/ec2/update.sh
```

Fallback without execute bit:

```bash
bash deploy/ec2/update.sh
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

## 8. Enable HTTPS (recommended)

This setup uses Caddy + Let's Encrypt (automatic cert issuance/renewal).

Requirements:
- You must have a domain name (TLS cert cannot be issued for raw EC2 public IP).
- DNS `A` record points your domain to this server public IP.
- Security group allows inbound `80` and `443`.

Example DNS:
- `lottery.example.com` -> `13.230.53.99`

Deploy with HTTPS:

```bash
cd ~/lottery-checker
chmod +x deploy/ec2/deploy-https.sh deploy/ec2/update-https.sh
# set DOMAIN and LETSENCRYPT_EMAIL in .env first
./deploy/ec2/deploy-https.sh
```

`deploy-https.sh` will stop the old HTTP-only stack automatically.

Update later:

```bash
cd ~/lottery-checker
./deploy/ec2/update-https.sh
```

Open:

```text
https://lottery.example.com/
```

## 9. Temporary HTTPS without your own domain

If you only need temporary HTTPS for demo/testing, use a tunnel.
Your app must already be running on this server at `http://localhost:80`.

### Option A: Cloudflare Quick Tunnel (no domain required)

Pros:
- No custom domain needed
- Quick start, free

Cons:
- URL changes each time you restart the tunnel
- Not for stable production URL

On server:

```bash
cd ~/lottery-checker
chmod +x deploy/ec2/tunnel-cloudflare.sh
./deploy/ec2/tunnel-cloudflare.sh
```

When started, it prints an HTTPS URL like `https://<random>.trycloudflare.com`.

### Option B: ngrok (temporary HTTPS URL)

Pros:
- Easy and popular for quick demos

Cons:
- Requires ngrok account + auth token
- URL may change (depending on plan)

On server:

```bash
cd ~/lottery-checker
chmod +x deploy/ec2/tunnel-ngrok.sh
export NGROK_AUTHTOKEN=<your_token>
./deploy/ec2/tunnel-ngrok.sh
```

ngrok will print a public HTTPS URL in terminal.

## 10. Admin page + DynamoDB search history

This app now has:
- `/admin`: traffic dashboard (protected by Basic Auth)
- DynamoDB persistence for search history with TTL cleanup
- Traffic counter ignores static assets and refresh duplicates (same IP + page path in short window)
- Traffic counter also ignores `/admin` and `/health` requests to reduce self-noise

### 10.1 Create DynamoDB table

Run from your local machine (AWS CLI configured).

Linux / macOS:

```bash
cd deploy/aws
chmod +x create-dynamodb-search-history.sh
./create-dynamodb-search-history.sh
```

Windows PowerShell:

```powershell
cd deploy\aws
.\create-dynamodb-search-history.ps1
```

Optional params:
- `TABLE_NAME` / `-TableName` (default: `lottery-checker-search-history`)
- `AWS_REGION` / `-AwsRegion` (default: `ap-northeast-1`)
- `TTL_ATTRIBUTE` / `-TtlAttribute` (default: `ttl_epoch`)

Manual AWS CLI equivalent:

```bash
aws dynamodb create-table \
  --table-name lottery-checker-search-history \
  --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
  --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region ap-northeast-1
```

Enable TTL on attribute `ttl_epoch`:

```bash
aws dynamodb update-time-to-live \
  --table-name lottery-checker-search-history \
  --time-to-live-specification Enabled=true,AttributeName=ttl_epoch \
  --region ap-northeast-1
```

TTL is asynchronous, so expired items may take up to about 48 hours to disappear.

### 10.2 EC2 IAM permission

Attach an instance role policy that allows:
- `dynamodb:PutItem`
- `dynamodb:Query`

on resource:
- `arn:aws:dynamodb:ap-northeast-1:<ACCOUNT_ID>:table/lottery-checker-search-history`

### 10.3 Configure env and deploy

Configure `.env` (recommended):

```bash
cd ~/lottery-checker
# starting from template
cp -n .env.example .env
# then edit .env values
# AWS_REGION=ap-northeast-1
# DYNAMODB_SEARCH_TABLE=lottery-checker-search-history
# SEARCH_HISTORY_TTL_DAYS=30
# ADMIN_USER=admin
# ADMIN_PASSWORD=<strong_password>
./deploy/ec2/deploy.sh
```

For HTTPS stack:

```bash
# set DOMAIN and LETSENCRYPT_EMAIL in .env
./deploy/ec2/deploy-https.sh
```

Open admin dashboard:

```text
https://<your-domain>/admin
```
