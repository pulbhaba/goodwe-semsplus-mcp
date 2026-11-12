#!/usr/bin/env bash

set -euo pipefail
set -a
. ./.env
set +a

REGION=${GOODWE_REGION:-au}
PORTAL="https://${REGION}-semsplus.goodwe.com"
UUID_HEX=$(openssl rand -hex 16)
UUID="${UUID_HEX:0:8}-${UUID_HEX:8:4}-4${UUID_HEX:13:3}-8${UUID_HEX:17:3}-${UUID_HEX:20:12}"
LOGIN_TS=$(date +%s%3N)
LOGIN_HASH=$(printf '%s' "$LOGIN_TS@@" | openssl dgst -sha256 | awk '{print $NF}')
LOGIN_SIGNATURE=$(printf '%s' "$LOGIN_HASH@$LOGIN_TS" | base64 | tr -d '\n')
LOGIN_JSON=$(
  jq -n --arg account "$GOODWE_USERNAME" --arg pwd "$GOODWE_PASSWORD" \
    '{account:$account,pwd:$pwd,agreement:1,isLocal:false,isChinese:false}' |
  curl -sS "$PORTAL/web/sems/sems-user/api/v1/auth/cross-login" \
    -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0' \
    -H 'Accept: application/json, text/plain, */*' \
    -H "Referer: $PORTAL/" \
    -H "Origin: $PORTAL" \
    -H "X-Signature: $LOGIN_SIGNATURE" \
    -H 'neutral: 0' \
    -H 'currentLang: en' \
    -H "uuid: $UUID" \
    -H 'os: Windows 10.0 desktop' \
    -H 'brand: Firefox 159.0 en-US Australia/Brisbane' \
    -H 'Token: {"uid":"","timestamp":0,"token":"","client":"semsPlusWeb","version":"","language":"en"}' \
    -H 'Content-Type: application/json' \
    --data-binary @-
)

if ! jq -e '
  .hasError != true and
  ((.code | tostring) == "0" or (.code | tostring) == "00000") and
  (.data | type == "object")
' <<<"$LOGIN_JSON" >/dev/null; then
  jq -c '{code,description,msg,traceId}' <<<"$LOGIN_JSON" >&2
  exit 1
fi

GW="$PORTAL/web/sems"

UserID=$(jq -r '.data.uid' <<<"$LOGIN_JSON")
TS=$(jq -r '.data.timestamp' <<<"$LOGIN_JSON")
RAW_TOKEN=$(jq -r '.data.token' <<<"$LOGIN_JSON")
TOKEN_JSON=$(jq -c --arg uuid "$UUID" \
  '.data + {version:"",client:"semsPlusWeb",language:"en",uuid:$uuid}' \
  <<<"$LOGIN_JSON")
HASH=$(printf '%s' "$TS@$UserID@$RAW_TOKEN" | openssl dgst -sha256 | awk '{print $NF}')
SIGNATURE=$(printf '%s' "$HASH@$TS" | base64 | tr -d '\n')

DAY=$(TZ=Australia/Brisbane date +%F)

curl --compressed --fail-with-body -sS "$GW/sems-plant/api/stations/statistics" \
  -X POST \
  -H 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:159.0) Gecko/20100101 Firefox/159.0' \
  -H 'Accept: application/json, text/plain, */*' \
  -H "Referer: $PORTAL/" \
  -H "X-Signature: $SIGNATURE" \
  -H "X-Uid: $UserID" \
  -H "X-Token: $RAW_TOKEN" \
  -H "X-Timestamp: $TS" \
  -H 'neutral: 0' \
  -H 'currentLang: en' \
  -H "uuid: $UUID" \
  -H 'os: Windows 10.0 desktop' \
  -H 'brand: Firefox 159.0 en-US Australia/Brisbane' \
  -H "Token: $TOKEN_JSON" \
  -H 'Content-Type: application/json' \
  -H "Origin: $PORTAL" \
  --data-binary @- <<JSON
{"stationId":"$GOODWE_STATION_ID","isReport":false,"items":["proDischarStats","proConsumStats","proCharStats","proSystemTotalStats","proGridStats","proPurchaseStats","proSelfConsumStats"],"dimension":"day","startTime":"$DAY 00:00:00","endTime":"$DAY 23:59:59"}
JSON
