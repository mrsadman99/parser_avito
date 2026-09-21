#!/data/data/com.termux/files/usr/bin/bash

# --- Настройки ---
CONFIG_FILE="/data/data/com.termux/files/usr/etc/tinyproxy/tinyproxy.conf"
TINYPROXY_BIN="tinyproxy"
UID_TERMUX=$(id -u)

# --- 1. Определяем мобильный интерфейс ---
IFACE=$(su -c "ip route | grep -oE 'rmnet[^ ]*|ccmni[^ ]*' | head -n1")

if [ -z "$IFACE" ]; then
    echo "Мобильный интерфейс не найден"
    exit 1
fi
echo "Мобильный интерфейс: $IFACE"

# --- 2. Получаем IP-адрес этого интерфейса ---
IP_MOBILE=$(su -c "ip -4 addr show $IFACE | awk '/inet /{print \$2}' | cut -d/ -f1 | head -n1")

if [ -z "$IP_MOBILE" ]; then
    echo "Не удалось получить IP для интерфейса $IFACE"
    exit 1
fi
echo "IP мобильного интерфейса: $IP_MOBILE"

# --- 3. Очистка старых правил (на случай повторного запуска) ---
su -c "iptables -t mangle -D OUTPUT -m owner --uid-owner $UID_TERMUX -m conntrack --ctstate NEW -j CONNMARK --set-mark 0x10" 2>/dev/null
su -c "iptables -t mangle -D OUTPUT -m connmark --mark 0x10 -j MARK --set-mark 0x10" 2>/dev/null
su -c "iptables -t mangle -D OUTPUT -m owner --uid-owner $UID_TERMUX -d 192.168.0.0/16 -j RETURN" 2>/dev/null
su -c "ip rule del fwmark 0x10 table 100" 2>/dev/null
su -c "ip route flush table 100" 2>/dev/null

# --- 4. Настраиваем маркировку и маршрутизацию ---
# Исключение: трафик к локальной подсети не помечаем
su -c "iptables -t mangle -A OUTPUT -m owner --uid-owner $UID_TERMUX -d 192.168.0.0/16 -j RETURN"

# Помечаем только новые исходящие соединения Termux
su -c "iptables -t mangle -A OUTPUT -m owner --uid-owner $UID_TERMUX -m conntrack --ctstate NEW -j CONNMARK --set-mark 0x10"

# Восстанавливаем метку на всех пакетах помеченного соединения
su -c "iptables -t mangle -A OUTPUT -m connmark --mark 0x10 -j MARK --set-mark 0x10"

# Маршрутизация помеченных пакетов через мобильный интерфейс
su -c "ip rule add fwmark 0x10 table 100"
su -c "ip route add default dev $IFACE table 100"

echo "Маршрутизация настроена: UID=$UID_TERMUX, интерфейс=$IFACE"

# --- 5. Обновляем Bind в конфиге tinyproxy ---
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Конфиг не найден: $CONFIG_FILE"
    exit 1
fi

if grep -qE '^[[:space:]]*Bind[[:space:]]' "$CONFIG_FILE"; then
    # Заменяем существующую строку Bind (в т.ч. закомментированную)
    sed -i -E "s|^[[:space:]]*#?[[:space:]]*Bind[[:space:]].*|Bind $IP_MOBILE|" "$CONFIG_FILE"
    echo "Строка Bind обновлена на $IP_MOBILE"
else
    # Добавляем строку, если её нет
    echo "Bind $IP_MOBILE" >> "$CONFIG_FILE"
    echo "Строка Bind добавлена: $IP_MOBILE"
fi
