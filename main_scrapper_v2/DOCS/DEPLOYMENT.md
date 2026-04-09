# News Scrapper — Deployment Guide

How to run the scrapper in production for long-term (months/years) operation.

---

## Basic: Run Directly

```bash
cd main_scrapper
python main.py
```

Stop with Ctrl+C. Not suitable for production — stops when terminal closes.

---

## Windows: Run as Background Service

### Option 1: Windows Task Scheduler

1. Open Task Scheduler → Create Basic Task
2. Name: "News Scrapper"
3. Trigger: "When the computer starts"
4. Action: Start a program
   - Program: `python.exe` (full path)
   - Arguments: `main.py`
   - Start in: `C:\Users\aaa\Desktop\latest_news_crawler\main_scrapper`
5. Properties → Check "Run whether user is logged on or not"
6. Settings → Uncheck "Stop the task if it runs longer than"

### Option 2: NSSM (Non-Sucking Service Manager)

```powershell
# Install NSSM
choco install nssm

# Create service
nssm install NewsScrapper python.exe
nssm set NewsScrapper AppDirectory C:\Users\aaa\Desktop\latest_news_crawler\main_scrapper
nssm set NewsScrapper AppParameters main.py
nssm set NewsScrapper Start SERVICE_AUTO_START

# Start service
nssm start NewsScrapper

# Check status
nssm status NewsScrapper

# View logs
nssm edit NewsScrapper  # change stdout/stderr to log files
```

### Option 3: PowerShell Background Job

```powershell
Start-Job -ScriptBlock {
    Set-Location C:\Users\aaa\Desktop\latest_news_crawler\main_scrapper
    python main.py
}
```

---

## Linux: Systemd Service

Create `/etc/systemd/system/news-scrapper.service`:

```ini
[Unit]
Description=News Scrapper Service
After=network.target redis.service

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/main_scrapper
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable news-scrapper
sudo systemctl start news-scrapper
sudo systemctl status news-scrapper
journalctl -u news-scrapper -f  # follow logs
```

---

## Docker (Optional)

### Dockerfile

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
CMD ["python", "-u", "main.py"]
```

### docker-compose.yml

```yaml
version: '3.8'
services:
  scrapper:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - ./DATA:/app/DATA
      - ./logs:/app/logs
    environment:
      - REDIS_URL=redis://redis:6379/0
    restart: always
    depends_on:
      - redis

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    restart: always

volumes:
  redis_data:
```

```bash
docker-compose up -d
docker-compose logs -f scrapper
```

---

## Monitoring in Production

### Health Checks

The dashboard at `http://your-server:8080/api/stats` returns JSON with:
- Worker statuses (healthy/degraded/blocked)
- Uptime
- Article counts

Use this for external monitoring:
```bash
# Simple health check
curl -s http://localhost:8080/api/stats | python -c "
import sys, json
d = json.load(sys.stdin)
workers = d.get('workers', {})
blocked = sum(1 for w in workers.values() if w['is_blocked'])
if blocked > 0:
    print(f'ALERT: {blocked} sources blocked')
    sys.exit(1)
print('OK')
"
```

### Data Backup

Schedule periodic backups of the DATA directory:
```bash
# Daily backup
tar -czf backup_$(date +%Y%m%d).tar.gz DATA/
```

---

## Resource Requirements

| Resource | Typical Usage |
|----------|--------------|
| CPU | <1% (mostly sleeping between polls) |
| RAM | ~50-100 MB (Python + sessions + seen-ID sets) |
| Disk | ~50 MB/month (JSON data) + 200 MB max (logs) |
| Network | ~5-15 GB/month (API calls, HTML scraping) |
| Redis | ~10 MB (seen-ID sets) |
