# Mac Mini как Production Server — Reliability Engineering

**Составлен:** 2026-06-18 | **Метод:** Deep research (5 search angles, 15+ sources, adversarial verification)
**Контекст:** SPA DeFi yield optimizer, локальный Mac Mini как primary compute, `launchd` daily cycle, $100K virtual capital, budget на improvements: $200–500.

---

## TL;DR — Приоритетные действия

| Приоритет | Action | Стоимость | Время |
|-----------|--------|-----------|-------|
| 🔴 P0 | UPS (CyberPower CP850PFCLCD) | $110 | 1 день |
| 🔴 P0 | 4G failover router (TP-Link ER605 V2 + USB modem) | $80–100 | 2 дня |
| 🟡 P1 | Hetzner CX22 VPS + rsync cold standby | $4/мес | 1 день |
| 🟡 P1 | Remote reboot (iBoot-G2 с AutoPing) | $150–175 | 1 день |
| 🟢 P2 | TG Pro thermal monitoring | $10 | 1 час |
| 🟢 P2 | smartmontools SSD health | бесплатно | 30 мин |
| 🟢 P2 | macOS update policy (отключить авто) | бесплатно | 15 мин |

**Итого бюджет P0+P1+P2:** ~$375–395 — укладывается в $500.

---

## 1. Hardware Reliability: MTTF для Mac Mini M2/M4

### Официальные данные
Apple **не публикует MTTF/MTBF** ни для одного Mac. В отличие от Dell/HPE, Apple не предоставляет показатели AFR (Annual Failure Rate). Сравнение с enterprise-hardware на уровне официальных цифр невозможно.

**Для сравнения:** Enterprise HDD/SSD: ~2 млн часов MTBF (AFR ~0.44%). Consumer NVMe SSD: ~1–1.5 млн часов MTBF (AFR ~0.6–0.9%).

### Real-World данные (анекдотические, но консистентные)
- Mac Mini 2012: работает 24/7 без сбоев **11+ лет** (MacRumors Forums, 2024)
- Mac Mini M4 Pro (production AI inference): **2 месяца без единого даунтайма** (acdigest.substack.com, May 2026)
- M1 Mac Mini (Plex/Home Assistant): **3+ года** стабильно
- Основная причина замены Mac Mini в сообществе — **устаревание ПО**, не hardware failure

**Исторический исключение:** Mac Mini Server 2014 (HDD-era) — 2 из 8 машин потеряли жёсткий диск за месяц (Jamf Nation, 2014). **Причина — механические диски**, не Apple Silicon. На NVMe-серии аналогичных кластерных отказов не зафиксировано.

### Провайдеры Mac Mini Colocation
- **Scaleway** (Франция): сотни Mac Mini в Tier III+ датацентре (Opcore DC2); 3N электричество, 3 генератора; fleet expansion продолжается — косвенное подтверждение приемлемой надёжности
- **macminicolo / Mac Mini Vault**: 10+ лет работы — бизнес-модель жизнеспособна только при нормальной надёжности оборудования
- **Unihost**: документирует 10–45W потребление, двойной PDU как компенсация single PSU

### Структурные риски Mac Mini vs Enterprise

| Параметр | Mac Mini M2/M4 | Enterprise Server (Dell/HPE) |
|----------|---------------|-------------------------------|
| ECC Memory | ❌ Нет | ✅ Стандарт |
| Redundant PSU | ❌ Один | ✅ Dual hot-swap |
| BMC/IPMI/iLO | ❌ Нет | ✅ Out-of-band mgmt |
| Hot-swap storage | ❌ Нет | ✅ Да |
| Ремонтопригодность | ❌ Логика впаяна | ✅ Компонентный ремонт |
| Remote firmware | ❌ Нет | ✅ Да |

**Ключевой риск для SPA:** Отсутствие ECC — возможна silent memory corruption без краша. При paper trading с виртуальным капиталом приемлемо; при live trading с реальными деньгами — серьёзный аргумент против Mac Mini как primary.

**Вывод:** Для SPA paper-trading цикла (daily, не HFT) Mac Mini M4 — **обоснованный выбор**. Надёжность hardware не будет основным слабым местом при правильной инфраструктуре. Реальный риск — питание, сеть и отсутствие remote management.

**Sources:**
- [Scaleway — How We Turn Mac mini Into High-Performance Servers](https://www.scaleway.com/en/blog/how-we-turn-apples-mac-mini-into-high-performance-dedicated-servers/)
- [acdigest.substack.com — Production Inference on Mac Mini M4 Pro](https://acdigest.substack.com/p/i-have-been-running-production-inference)
- [MacRumors Forums — Mac Mini Longevity](https://forums.macrumors.com/threads/mac-mini-longevity.2413458/)
- [OakHost — Overcoming Difficulties of Mac Minis in a Data Center](https://www.oakhost.com/blog/overcoming-mac-mini-data-center-difficulties/)

---

## 2. UPS: Рекомендации для Mac Mini

### Потребление энергии (измеренное, не spec)

| Модель | Idle (wall-plug) | Пиковая нагрузка | Apple spec max |
|--------|-----------------|------------------|----------------|
| Mac Mini M2 | ~7W | ~30W | 150W |
| Mac Mini M4 (base) | **3–6W** | **40–45W** | 65W |
| Mac Mini M4 Pro | ~25–30W (idle) | до 155W | 155W |

Измерения: ServeTheHome (4–6W idle M4), Jeff Geerling (3–4W idle M4), Apple Support (официальные spec).

### Критическое требование: Pure Sine Wave
Apple Silicon Mac используют **Active PFC блоки питания**. Simulated/stepped sine wave UPS вызывает:
- Гудение блока питания
- Перегрев
- Отключение при переходе на батарею

**Всегда выбирать UPS с pure sine wave output.**

### Рекомендуемые продукты

#### 🥇 Лучший выбор до $120: CyberPower CP850PFCLCD
- **Цена:** $100–120
- **Параметры:** 850VA / 510W, pure sine wave (PFC Sinewave)
- **Runtime:** ~20–30 минут с Mac Mini + монитор при типичной нагрузке
- **Функции:** LCD дисплей, 10 розеток, USB порт для macOS PowerPanel (автоматическое безопасное выключение)
- **Размер:** Mini-tower, сменная батарея
- [Amazon](https://www.amazon.com/CyberPower-CP850PFCLCD-Sinewave-Outlets-Mini-Tower/dp/B00429N18S) | [Newegg](https://www.newegg.com/cyberpower-cp850pfclcd/p/N82E16842102131)

#### 🥈 Лучший overall до $200: CyberPower CP1500PFCLCD
- **Цена:** $160–190
- **Параметры:** 1500VA / 1000W, pure sine wave
- **Преимущество:** Запас мощности если добавится Switch, NAS, монитор
- Та же экосистема CyberPower PowerPanel для macOS

#### 🥉 Альтернатива APC: APC Back-UPS Pro BR1000MS
- **Цена:** $150–180
- **Параметры:** 1000VA / 600W, true sine wave
- **Функции:** 10 розеток (6 battery + 4 surge), USB-A + USB-C зарядка, нативная интеграция с macOS
- [Amazon](https://www.amazon.com/APC-Sinewave-Battery-Protector-BR1000MS/dp/B0779KYKLB)

#### ❌ Избегать: APC Back-UPS BX1000M (~$110)
Stepped sine wave — не рекомендуется для Active PFC блоков питания Apple.

### macOS интеграция
**CyberPower PowerPanel Personal for Mac** (бесплатно):
- Автоматическое безопасное выключение при разряде батареи
- Мониторинг состояния UPS
- [Скачать](https://www.cyberpowersystems.com/product/software/power-panel-personal/powerpanel-personal-mac/)

**Sources:**
- [Apple Support — Mac mini power consumption](https://support.apple.com/en-us/103253)
- [Jeff Geerling — M4 Mac mini's efficiency is incredible](https://www.jeffgeerling.com/blog/2024/m4-mac-minis-efficiency-incredible/)
- [ServeTheHome — Apple Mac Mini M4 Review](https://www.servethehome.com/the-apple-mac-mini-m4-sets-the-mini-computer-standard/3/)
- [iMore — Best UPS for Mac 2026](https://www.imore.com/best-ups-battery-backups-your-mac)

---

## 3. Network Failover: 4G/LTE + Dual ISP

### Как работает failover (без маркетинга)
Роутер мониторит WAN через ICMP ping к внешнему IP (8.8.8.8 или 1.1.1.1). При потере ответов — переключается на backup link.

**⚠️ Критическая ошибка конфигурации:** Не используй режим "Member Down" — оптический ONT остаётся физически включённым при outage ISP, и "Member Down" никогда не сработает. Используй только **"Packet Loss"** health checks.

**Время failover:** Не публикуется ни одним вендором. По независимым измерениям pfSense: ~60 сек по умолчанию, настраивается до ~10 сек (риск false positives).

### Рекомендации по продуктам

#### Бюджет до $100: TP-Link ER605 V2 + USB LTE модем
- **Роутер:** $50 ([Amazon](https://www.amazon.com/TP-Link-Integrated-Lightening-Protection-TL-R605/dp/B08QTXNWZ1))
- **USB LTE модем:** $25–50 (дополнительно, например Huawei E3372)
- **Параметры:** 3× Gigabit WAN + 1× USB WAN, автоматический failover, load balancing, 50× OpenVPN, Omada SDN
- **Внимание:** USB WAN — только в **версии V2**. Обязательно проверяй перед покупкой
- **SIM карта:** AT&T/Verizon 4G failover plan ~$10/мес (1GB включено)
- **Итого:** $80–100 роутер + $10/мес SIM

#### Бюджет до $200: Teltonika RUT241 (★ Рекомендуется)
- **Цена:** $150–200
- **Параметры:** Встроенный Cat 4 LTE (150/50 Mbps), 1× WAN + 1× LAN, алюминиевый корпус (-40°C до +75°C)
- **Плюс:** Поддерживает все US bands (AT&T, T-Mobile, Verizon), промышленная надёжность, scriptable RutOS
- **Минус:** Fast Ethernet (100 Mbps), не Gigabit — ограничение для гигабитного интернета
- [Novotech](https://novotech.com/pages/best-failover-routers-for-2025)

#### Premium ($380): GL.iNet GL-X3000 Spitz AX
- **Цена:** $380 ([GL.iNet Store](https://store-us.gl-inet.com/products/spitz-ax-gl-x3000-wi-fi-6-4g-lte-5g-nrdual-sim-openwrt-c19g))
- **Параметры:** 5G NR / 4G LTE Cat 16, **dual SIM** (автоматическое переключение между операторами), Wi-Fi 6 AX3000, 4 failover пути (Ethernet + Cellular + Repeater + Tethering), OpenWrt
- **Лучший overall** если бюджет позволяет

#### Опция с батареей: GL.iNet GL-XE3000 Puli AX
- **Цена:** $410 ([GL.iNet Store](https://store-us.gl-inet.com/products/puli-ax-xe3000-wi-fi-6-5g-cellular-router-with-battery))
- **Дополнительно:** Встроенная батарея 6,400 mAh — роутер работает ~8 часов без электричества
- **Killer feature:** Защищает и от ISP outage, и от power outage одновременно

#### DIY / Homelab: OPNsense или pfSense на mini-PC
- **Стоимость:** $150–300 за N5105 mini-PC с dual NIC
- **Плюс:** Полный контроль, безлимитные WAN шлюзы, детальная настройка health checks
- **Минус:** Требует понимания сетей; 1–4 часа первоначальной настройки
- [OPNsense Multi-WAN Guide](https://docs.opnsense.org/manual/how-tos/multiwan.html)

### ❌ Не покупать
- **Netgear Orbi LBR20** — задокументированные проблемы с failover, требует ручной перезагрузки
- **Load Balancing mode** — ломает port forwarding, VPN, DDNS (публичный IP чередуется между соединениями)

**Sources:**
- [5GStore — Failover Internet Solutions](https://5gstore.com/blog/2024/12/31/failover-internet-solutions/)
- [GL.iNet — Spitz AX Failover Use Case](https://www.gl-inet.com/usecases/integrating-spitz-ax-as-a-cellular-failover-network/)
- [cornerofficehq.com — Best WAN Failover Routers 2025](https://cornerofficehq.com/best-wan-failover-routers/)
- [OPNsense Multi-WAN](https://docs.opnsense.org/manual/how-tos/multiwan.html)

---

## 4. Thermal Monitoring при 24/7 нагрузке

### Температурные пороги (реальные данные сообщества)

| Компонент | Нормальный idle | Под нагрузкой | Throttle point | Max рекомендуемый 24/7 |
|-----------|----------------|---------------|----------------|------------------------|
| CPU die (M4) | 39–45°C | 80–90°C | ~105°C | **85°C** |
| GPU (M4) | 40–55°C | 80–100°C | ~105°C | **85°C** |
| NVMe SSD | 30–45°C | 45–55°C | 70°C (риск) | **55°C** |
| Ambient | — | — | Apple spec: 35°C max | **ниже 25°C** |

M4 Mac Mini (non-Pro): при обычных server workloads (HTTP, JSON, cron) никогда не приближается к throttle point. Apple Silicon архитектурно эффективна при низких нагрузках.

### Инструменты: что установить

#### TG Pro (★ Primary recommendation) — $10
- **URL:** [tunabellysoftware.com/tgpro](https://www.tunabellysoftware.com/tgpro/)
- **Версия:** 2.103 (March 2026), поддерживает M1–M5
- **Функции:**
  - Мониторинг всех сенсоров (CPU per-core, GPU, SSD, WiFi, батарея, ambient)
  - **Auto Boost Rules** — автоматическое управление вентилятором по температуре
  - Email alerts при превышении порога
  - CSV logging всех сенсоров с timestamp
  - Fan control на M4 (добавлен в версии 2.97)
- **Рекомендуемая настройка для SPA:**
  - Создать Auto Boost Rule: CPU die > 80°C → fan +30%; > 85°C → fan Max
  - Email alert при CPU die > 90°C

#### iStat Menus — ~$10/мес (Setapp) или отдельно
- **URL:** [bjango.com/mac/istatmenus](https://bjango.com/mac/istatmenus/)
- Все системные метрики в menu bar: CPU, GPU, RAM, сеть, диск, темп
- Версия 7 полностью поддерживает Apple Silicon сенсоры (после установки helper app)

#### Macs Fan Control — Бесплатно (альтернатива)
- **URL:** [macsfancontrol.net](https://macsfancontrol.net/)
- ⚠️ Known issues с M3; для M4 использовать TG Pro

### SSD Health Monitoring: smartmontools

```bash
# Установка
brew install smartmontools

# Проверка здоровья
sudo smartctl -a disk0

# Ключевые метрики для NVMe
# - SMART overall-health: PASSED / FAILED
# - Available Spare (%): должен быть > 10%
# - Percentage Used: ресурс записи (при 100% — износ)
# - Media and Data Integrity Errors: всегда должно быть 0
# - Unsafe Shutdowns: смотреть динамику (скачок = аварийное отключение)
```

**Рекомендация:** Еженедельный cron: `sudo smartctl -a disk0 >> /tmp/ssd_health_weekly.log`

### Memory Pressure мониторинг

```bash
# Текущее давление (выводит: System memory pressure: N%)
memory_pressure

# Swap usage
sysctl vm.swapusage

# Непрерывный мониторинг (1 сек интервал)
vm_stat 1
```

**Интерпретация memory_pressure:**
- < 50%: Green — всё хорошо
- 50–70%: Yellow — начинается компрессия, но ещё ОК
- > 70%: Red — активный swap → ускоренный износ SSD → выяснить причину

**Встроить в SPA launchd:** Добавить logging memory pressure каждые 15 минут (аналогично `spa_cycle`) в `/tmp/spa_memory_pressure.log`.

**Sources:**
- [TG Pro — Tunabelly Software](https://www.tunabellysoftware.com/tgpro/)
- [smartctl macOS guide — OSXDaily](https://osxdaily.com/2024/04/10/how-to-check-disk-health-on-mac-with-smartctl/)
- [Activity Monitor Memory — Apple Support](https://support.apple.com/guide/activity-monitor/view-memory-usage-actmntr1004/mac)
- [MacRumors — Mac Mini M4 Thermals](https://forums.macrumors.com/threads/mac-mini-m4-thermals.2442671/)

---

## 5. Cold Standby на Hetzner VPS

### Архитектура

```
Mac Mini (Primary) ─── rsync (каждые 15 мин) ──► Hetzner CX22 VPS (Standby)
                                                        │
                         Watchdog (каждые 2 мин) ◄──────┘
                                 │
                         Primary не отвечает?
                                 │
                    ┌────────────┴────────────┐
                    │                         │
              Hetzner Failover IP            Start spa-cycle.service
              переключается на VPS           на VPS (из последнего rsync)
              (90–110 сек)
```

### Шаг 1: Выбор VPS

**Hetzner CX22** — рекомендуется:
- 2 vCPU, 4GB RAM, 40GB SSD
- **~€4/месяц** (~$4.50)
- Локации: Нюрнберг (NBG1), Хельсинки (HEL1), Фалькенштайн (FSN1)
- Hetzner Robot API для управления Failover IP

**Регистрация:** [hetzner.com/cloud](https://www.hetzner.com/cloud)

### Шаг 2: rsync синхронизация (cron, каждые 15 минут)

```bash
# На Mac Mini: создать SSH ключ
ssh-keygen -t ed25519 -f ~/.ssh/hetzner_spa_key -N ""
ssh-copy-id -i ~/.ssh/hetzner_spa_key.pub root@<HETZNER_VPS_IP>

# crontab -e на Mac Mini:
*/15 * * * * rsync -az --delete \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/ \
  -e "ssh -i /Users/yuriikulieshov/.ssh/hetzner_spa_key -o StrictHostKeyChecking=no" \
  root@<HETZNER_VPS_IP>:/srv/spa/data/ \
  >> /tmp/spa_rsync.log 2>&1
```

**Максимальная потеря данных:** 15 минут — для daily цикла SPA это абсолютно приемлемо.

**С версионированием (рекомендуется):**
```bash
*/15 * * * * rsync -az --delete \
  --backup --backup-dir=/srv/spa/data-backup/$(date +%Y%m%d-%H%M) \
  /Users/yuriikulieshov/Documents/SPA_Claude/data/ \
  -e "ssh -i /Users/yuriikulieshov/.ssh/hetzner_spa_key" \
  root@<HETZNER_VPS_IP>:/srv/spa/data/
```

### Шаг 3: Watchdog скрипт на VPS

```bash
#!/bin/bash
# /srv/spa/watchdog.sh — запускать каждые 2 минуты через cron
PRIMARY_IP="<MAC_MINI_PUBLIC_IP>"
FAILOVER_IP="<HETZNER_FAILOVER_IP>"
STANDBY_IP="<HETZNER_VPS_IP>"
ROBOT_USER="<HETZNER_ROBOT_USER>"
ROBOT_PASS="<HETZNER_ROBOT_PASS>"

FAILURE_COUNT_FILE="/tmp/spa_primary_failures"

if ! ping -c 3 -W 5 "$PRIMARY_IP" > /dev/null 2>&1; then
  count=$(cat "$FAILURE_COUNT_FILE" 2>/dev/null || echo 0)
  count=$((count + 1))
  echo $count > "$FAILURE_COUNT_FILE"

  # Срабатывать только после 3 последовательных неудач (6 минут)
  if [ "$count" -ge 3 ]; then
    echo "$(date): Primary DOWN after $count checks — activating failover" >> /tmp/spa_failover.log

    # Переключить Hetzner Failover IP на VPS
    curl -s -u "$ROBOT_USER:$ROBOT_PASS" \
      "https://robot-ws.your-server.de/failover/$FAILOVER_IP" \
      -d "active_server_ip=$STANDBY_IP" >> /tmp/spa_failover.log 2>&1

    # Запустить SPA cycle на VPS
    # (нужен Python 3 + копия репозитория на VPS)
    systemctl start spa-cycle.service
    echo 0 > "$FAILURE_COUNT_FILE"
  fi
else
  echo 0 > "$FAILURE_COUNT_FILE"
fi
```

```bash
# Cron на VPS:
*/2 * * * * /srv/spa/watchdog.sh
```

### Шаг 4: Настройка SPA на VPS

```bash
# На Hetzner VPS:
apt-get install -y python3 rsync

# Клонировать репозиторий (или rsync push весь код тоже)
git clone https://github.com/YourUser/SPA_Claude.git /srv/spa/repo

# Launchd на VPS заменить на systemd:
# /etc/systemd/system/spa-cycle.service
[Unit]
Description=SPA Daily Cycle
After=network.target

[Service]
Type=oneshot
User=root
WorkingDirectory=/srv/spa/repo
ExecStart=/usr/bin/python3 -m spa_core.paper_trading.cycle_runner --verbose
StandardOutput=append:/tmp/spa_cycle_vps.log
StandardError=append:/tmp/spa_cycle_err_vps.log

[Install]
WantedBy=multi-user.target
```

**Важно:** На VPS нет macOS Keychain — секреты (если нужны) хранить в environment variables через systemd EnvironmentFile.

### Timeline failover

| Шаг | Время |
|-----|-------|
| Watchdog детектирует падение (3 проверки по 2 мин) | 0–6 мин |
| Hetzner Failover IP re-route через API | +90–110 сек |
| SPA cycle_runner запускается на VPS | +1 мин |
| DNS/Cloudflare tunnel обновляется | +1–5 мин |
| **Итого** | **~10–12 минут** |

Цель < 30 минут — выполняется с запасом.

### Альтернатива: Hetzner Storage Box (только данные, без compute failover)
- От €3.29/мес за 100GB
- rsync через SSH port 23: `rsync -az -e 'ssh -p 23' data/ u123456@u123456.your-storagebox.de:/spa-data/`
- Хорошо как дополнительный backup tier, не заменяет VPS для failover

**Sources:**
- [Hetzner Community — Failover Script](https://community.hetzner.com/tutorials/failover-script)
- [Hetzner Docs — Failover IP](https://docs.hetzner.com/robot/dedicated-server/ip/failover/)
- [hostaccent.com — Linux VPS Backup via rsync+cron](https://www.hostaccent.com/blog/linux-vps-backup-automation-rsync-cron)
- [Hetzner Storage Box — rsync/Borg access](https://docs.hetzner.com/storage/storage-box/access/access-ssh-rsync-borg)

---

## 6. macOS Updates: управление без downtime

### Принципиальная проблема
Начиная с macOS Big Sur (2021), Apple **убрала возможность заблокировать обновления через CLI** (`softwareupdate`). Максимальный официальный дефер — 90 дней (только через MDM). Без MDM — только ручное управление.

### Стратегия для SPA (без MDM)

**Шаг 1: Отключить автоматическую установку обновлений**
```
System Settings → General → Software Update → (i) кнопка →
Отключить: "Install macOS updates"
Оставить включённым: "Check for updates" (чтобы видеть что доступно)
```

**Шаг 2: Расписание обновлений**
- Проверять наличие обновлений каждую пятницу вечером
- Устанавливать только в субботу/воскресенье, когда daily cycle уже прошёл
- SPA daily cycle: `08:00` — устанавливать обновления после `09:00` в выходные

**Шаг 3: Pre-download без install**
```bash
# Скачать обновления заранее (без установки)
sudo softwareupdate --download --recommended

# Просмотр доступных обновлений
softwareupdate --list
```

**Шаг 4: Graceful shutdown перед update**
```bash
# Дождаться завершения текущего цикла, затем:
launchctl stop com.spa.daily_cycle
# Убедиться что нет активных операций:
ps aux | grep spa
# Установить обновление:
sudo softwareupdate --install --recommended
```

**Шаг 5: После reboot — verify**
```bash
# Убедиться что launchd сервисы подняты:
launchctl list | grep com.spa
# Прогнать тест cycle:
python3 -m spa_core.paper_trading.golive_checker
```

### MDM (при масштабировании)
Если понадобится формальный деференс обновлений: **Mosyle Personal** (бесплатно для ≤5 устройств) или **Jamf Now** (от $4/устройство/мес). Позволяет defer major updates до 90 дней и планировать minor patch installation window.

---

## 7. Remote Access: удалённый reboot при зависании

### Проблема
Mac Mini без physical access:
1. Завис (не пингуется) — нужен hard power cycle
2. Завис на pre-boot (FileVault) — нужен KVM (экран + клавиатура)

### Варианты

#### iBoot-G2 (★ Best для авто-reboot) — $150–175
- **Тип:** Smart PDU, 1 розетка
- **URL:** [dataprobe.com/products/iboot-g2](https://www.dataprobe.com/products/iboot-g2) | [Amazon](https://www.amazon.com/Dataprobe-iBoot-G2-Network-Automation-Rebooting/dp/B00B0YJUPQ)
- **Цена:** $225 (list) / $150–175 (Amazon/eBay)
- **🌟 AutoPing feature:** Постоянно пингует Mac Mini. Если нет ответа → автоматически отключает/включает питание. **Нулевое человеческое вмешательство.**
- **Как настроить для SPA:** Target ping = внешний IP Mac Mini или localhost + порт SPA HTTP server (8765)
- **Веб-интерфейс:** Контроль через браузер или Dataprobe облако

#### JetKVM (★ Best для полного KVM) — $103
- **Тип:** IP KVM (экран + клавиатура + мышь удалённо)
- **URL:** [jetkvm.com](https://jetkvm.com/) | [Micro Center](https://www.microcenter.com/product/706012/jetkvm-ip-kvm) | [Amazon](https://www.amazon.com/Open-Source-Touchscreen-ATX-Extension-Board/dp/B0GJK4659C)
- **Цена:** $103 (retail, Kickstarter был $69)
- **Спецификации:** RockChip ARM Cortex-A7, 256MB, 16GB eMMC, 1080p/60fps H.264, 30–60ms latency, 1.69" touchscreen
- **Для Mac Mini M4:** Подтверждённая совместимость; работает с FileVault pre-boot screen
- **Доступ:** WebRTC через бесплатное облако (за NAT) или self-hosted; open source (Go + React)
- **Power control:** RJ12 Extension порт + DC Power Control extension (доп. аксессуар) для управления питанием; для Mac Mini — через USB relay или smart plug

#### PiKVM V4 Mini (DIY альтернатива) — $130–160
- **URL:** [pikvm.org](https://pikvm.org/products/) | [PiShop US](https://www.pishop.us/product/pikvm-v4-mini/)
- **Цена:** $130–160 (assembled + CM4)
- **Преимущество над JetKVM:** Hardware watchdog (перезапускает сам PiKVM при зависании), mPCIe слот для LTE
- **ATX control:** Для Mac Mini подключается через USB relay к smart plug

#### Monoprice Blackbird Pro Smart PDU (4 розетки) — $80–120
- **URL:** [monoprice.com](https://www.monoprice.com/product?p_id=44572)
- **Параметры:** 4 розетки, TCP/IP web interface, SNMP v1/v2/v3, TLS 1.2
- **Для SPA:** Одна розетка — Mac Mini, одна — роутер; независимое управление
- Не имеет AutoPing (в отличие от iBoot-G2) — только ручное управление через web

### Рекомендуемая конфигурация

**Tier 1 (оптимально, $250–280):**
- **JetKVM** ($103) — полный KVM для диагностики и recovery
- **iBoot-G2** ($150–175) — AutoPing для авто-reboot при полном зависании
- Итого: $253–278 — в бюджете $500

**Tier 2 (бюджетно, $150–175):**
- **iBoot-G2** ($150–175) alone — только AutoPing reboot, без KVM доступа
- Достаточно для сценария "Mac Mini завис и не пингуется"

**Sources:**
- [JetKVM official site](https://jetkvm.com/)
- [PiKVM V4 products](https://pikvm.org/products/)
- [Dataprobe iBoot-G2](https://www.dataprobe.com/products/iboot-g2)
- [Monoprice Blackbird Pro PDU](https://www.monoprice.com/product?p_id=44572)

---

## 8. Мониторинг: macOS-специфичные метрики

### Критические метрики для production

| Метрика | Инструмент | Команда / Метод | Alert threshold |
|---------|------------|-----------------|-----------------|
| CPU температура | TG Pro | GUI + email alert | > 90°C |
| SSD Percentage Used | smartmontools | `sudo smartctl -a disk0` | > 80% |
| Available Spare (SSD) | smartmontools | `sudo smartctl -a disk0` | < 15% |
| Memory Pressure | CLI | `memory_pressure` | > 70% |
| Swap Used | CLI | `sysctl vm.swapusage` | > 4GB |
| Free disk space | CLI | `df -h /` | < 10GB |
| launchd cycle health | launchctl | `launchctl list \| grep com.spa` | любой сервис не running |
| SPA equity curve gap | gap_monitor.py | `data/gap_monitor.json` | gap > 0 |
| HTTP server (port 8765) | curl | `curl -s localhost:8765/health` | non-200 |

### Скрипт мониторинга для SPA

Добавить launchd plist для запуска каждые 15 минут:

```bash
#!/bin/bash
# /Users/yuriikulieshov/Documents/SPA_Claude/scripts/health_check.sh

LOG="/tmp/spa_health_$(date +%Y%m%d).log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Memory pressure
MEM_PRESSURE=$(memory_pressure | grep -oP '\d+(?=%)')
# Swap
SWAP=$(sysctl vm.swapusage | grep -oP 'used = \K[0-9.]+[MG]')
# Free disk
DISK_FREE=$(df -BG / | awk 'NR==2{print $4}' | sed 's/G//')
# launchd spa cycle
SPA_CYCLE=$(launchctl list com.spa.daily_cycle 2>/dev/null | grep -c PID || echo 0)

echo "$TIMESTAMP | mem_pressure=${MEM_PRESSURE}% | swap=${SWAP} | disk_free=${DISK_FREE}GB | spa_launchd=${SPA_CYCLE}" >> "$LOG"

# Alert conditions
if [ "${MEM_PRESSURE}" -gt 70 ]; then
  echo "$TIMESTAMP ALERT: Memory pressure ${MEM_PRESSURE}% > 70%" >> "$LOG"
fi

if [ "${DISK_FREE}" -lt 10 ]; then
  echo "$TIMESTAMP ALERT: Disk free ${DISK_FREE}GB < 10GB" >> "$LOG"
fi
```

### SSD wear tracking (еженедельно)

```bash
# Добавить в crontab:
# 0 9 * * 1 (каждый понедельник в 09:00)
0 9 * * 1 sudo smartctl -a disk0 | grep -E "(SMART overall|Available Spare|Percentage Used|Power On Hours|Media and Data)" >> /tmp/ssd_health_weekly.log
```

**Sources:**
- [Activity Monitor Memory — Apple](https://support.apple.com/guide/activity-monitor/view-memory-usage-actmntr1004/mac)
- [SSD health monitoring — OWC/Rocket Yard](https://eshop.macsales.com/blog/80464-how-to-check-your-mac-ssd-health/)
- [TG Pro User Guide](https://www.tunabellysoftware.com/support/tgpro_tutorial/)
- [Memory pressure logging — Medium](https://medium.com/@laclementine/daily-logs-for-memory-pressure-and-swap-in-macos-f5b09d67c523)

---

## Сводный бюджет: $200–500

| Компонент | Продукт | Цена | Приоритет |
|-----------|---------|------|-----------|
| **UPS** | CyberPower CP850PFCLCD | $110 | 🔴 P0 |
| **Network failover** | TP-Link ER605 V2 + USB LTE modem + SIM | $90 + $10/мес | 🔴 P0 |
| **VPS standby** | Hetzner CX22 | $4.50/мес | 🟡 P1 |
| **Remote reboot** | Dataprobe iBoot-G2 | $155 | 🟡 P1 |
| **Thermal monitoring** | TG Pro | $10 | 🟢 P2 |
| **SSD monitoring** | smartmontools | $0 (brew) | 🟢 P2 |
| | | | |
| **ИТОГО единовременно** | | **~$365** | |
| **+ ежемесячно** | VPS $4.50 + SIM $10 | **$14.50/мес** | |

**Экономия vs. Tier 2 (с JetKVM вместо iBoot-G2 + GL.iNet вместо TP-Link):**
- Tier 2: $110 + $203 (JetKVM+PDU) + $380 (GL-X3000) + $4.50 + $10 = ~$707 — **выходит за $500**
- Tier 1 выше: $365 единовременно — **укладывается в $500 с запасом**

---

## Risk Matrix: до и после improvements

| Риск | Вероятность | Impact | Mitigation | Остаточный риск |
|------|-------------|--------|------------|-----------------|
| Power outage | Средняя | High | UPS CP850PFCLCD | Низкий (30 мин battery) |
| ISP outage | Средняя | High | 4G failover router | Низкий (авто-переключение) |
| Mac Mini freeze | Низкая | Medium | iBoot-G2 AutoPing | Очень низкий (авто-reboot) |
| SSD failure | Очень низкая | Critical | rsync → Hetzner VPS | Средний (15 мин lag) |
| Mac Mini hardware failure | Очень низкая | Critical | Hetzner VPS failover | Средний (~12 мин failover) |
| Thermal throttling | Очень низкая | Low | TG Pro + alert | Очень низкий |
| macOS update downtime | Низкая | Low | Manual scheduling | Очень низкий |
| Memory corruption (no ECC) | Очень низкая | Medium | Atomic writes, checksums | Принято (paper trading) |

---

## Следующие шаги

1. **Сегодня (бесплатно, 30 мин):**
   - `brew install smartmontools && sudo smartctl -a disk0` — baseline SSD health
   - Отключить автообновление macOS (System Settings → Software Update)
   - `memory_pressure` — проверить baseline

2. **На этой неделе ($110):**
   - Заказать CyberPower CP850PFCLCD
   - Настроить CyberPower PowerPanel Personal для автошатдауна

3. **Следующая неделя ($90–100):**
   - TP-Link ER605 V2 + USB LTE модем + SIM карта
   - Настроить failover с "Packet Loss" health checks

4. **В течение месяца ($155 + $4.50/мес):**
   - Dataprobe iBoot-G2: настроить AutoPing на Mac Mini IP
   - Hetzner CX22: rsync cron + watchdog скрипт + systemd для SPA

5. **Опционально ($10):**
   - TG Pro: настроить Auto Boost Rules и email alerts

---

*Отчёт составлен: 2026-06-18. Метод: deep research (5 search angles, 15+ sources, adversarial verification). Все цены актуальны на дату составления — верифицировать перед покупкой.*
