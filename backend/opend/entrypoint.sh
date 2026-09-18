#!/bin/bash
set -e

cd /opt/opend/FutuOpenD

mkdir -p /opt/opend/FutuOpenD/Log
chmod 777 /opt/opend/FutuOpenD/Log

if [ "$#" -gt 0 ]; then
	exec ./OpenD "$@"
fi

args=()

if [ -n "${MOOMOO_LOGIN_ACCOUNT:-}" ]; then
	args+=("-login_account=${MOOMOO_LOGIN_ACCOUNT}")
fi

if [ -n "${MOOMOO_LOGIN_PASSWORD:-}" ]; then
	args+=("-login_pwd=${MOOMOO_LOGIN_PASSWORD}")
elif [ -n "${MOOMOO_LOGIN_PASSWORD_MD5:-}" ] && [[ "${MOOMOO_LOGIN_PASSWORD_MD5}" =~ ^[0-9a-fA-F]{32}$ ]]; then
	args+=("-login_pwd_md5=${MOOMOO_LOGIN_PASSWORD_MD5}")
fi

if [ -n "${MOOMOO_LOGIN_REGION:-}" ]; then
	args+=("-login_region=${MOOMOO_LOGIN_REGION}")
fi

args+=("-lang=${MOOMOO_LANG:-en}")
args+=("-log_level=${MOOMOO_LOG_LEVEL:-info}")
if [ "${MOOMOO_CONSOLE:-0}" = "1" ]; then
	args+=("-console=1")
fi

CFG_FILE=/tmp/OpenD.runtime.xml
RSA_KEY_PATH="${MOOMOO_OPEND_RSA_PRIVATE_KEY_PATH:-}"
cat > "$CFG_FILE" <<EOF
<moomoo_opend>
  <ip>${MOOMOO_API_IP:-0.0.0.0}</ip>
  <api_port>${MOOMOO_API_PORT:-11111}</api_port>
  <lang>${MOOMOO_LANG:-en}</lang>
  <log_level>${MOOMOO_LOG_LEVEL:-info}</log_level>
  <telnet_ip>${MOOMOO_TELNET_IP:-127.0.0.1}</telnet_ip>
  <telnet_port>${MOOMOO_TELNET_PORT:-22222}</telnet_port>
  <price_reminder_push>1</price_reminder_push>
  <auto_hold_quote_right>1</auto_hold_quote_right>
  <future_trade_api_time_zone>${MOOMOO_FUTURE_TRADE_API_TIME_ZONE:-UTC+9}</future_trade_api_time_zone>
</moomoo_opend>
EOF

if [ -n "$RSA_KEY_PATH" ]; then
	if [ ! -f "$RSA_KEY_PATH" ]; then
		echo "RSA private key file not found: $RSA_KEY_PATH" >&2
		exit 1
	fi
	sed -i "s#</moomoo_opend>#  <rsa_private_key>${RSA_KEY_PATH}</rsa_private_key>\\n</moomoo_opend>#" "$CFG_FILE"
fi

args+=("-cfg_file=${CFG_FILE}")

# OpenD へ後からコマンドを流せるように FIFO を常設する。
FIFO=/tmp/opend_input
rm -f "$FIFO"
mkfifo "$FIFO"

# backendは共有ボリューム上の制御ファイルへ書き込み、ここでOpenDのFIFOへ中継する。
CONTROL_FILE="${OPEND_CONTROL_PATH:-/root/.com.moomoo.OpenD/opend_input}"
mkdir -p "$(dirname "$CONTROL_FILE")"
rm -f "$CONTROL_FILE"

(
	while true; do
		if [ -s "$CONTROL_FILE" ]; then
			cat "$CONTROL_FILE" >&3
			rm -f "$CONTROL_FILE"
		else
			sleep 0.2
		fi
	done
) &
_control_pid=$!

# FIFO を read/write で開いて、OpenD 側と中継側のどちらもブロックしにくくする。
exec 3<>"$FIFO"

./OpenD "${args[@]}" < "$FIFO" &
_open_pid=$!

if [ -n "${MOOMOO_PIC_VERIFY_CODE:-}" ]; then
	(
		sleep "${MOOMOO_PIC_VERIFY_DELAY:-5}"
		printf "input_pic_verify_code -code=%s\n" "${MOOMOO_PIC_VERIFY_CODE}" >&3
	) &
fi

wait "$_open_pid"
kill "$_control_pid" 2>/dev/null || true
