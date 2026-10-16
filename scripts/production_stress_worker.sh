#!/usr/bin/env bash
set -u

BASE_URL="${BASE_URL:-https://pelagia.onrender.com}"
RUN_ID="${1:?run id required}"
START_INDEX="${2:?start index required}"
COUNT="${3:?count required}"
OUT_DIR="${OUT_DIR:-stress_results}"
PHOTO_FILE="${PHOTO_FILE:-pelagia/static/img/ocean-satellite.png}"

mkdir -p "$OUT_DIR"
LOG_FILE="$OUT_DIR/${RUN_ID}_${START_INDEX}_$((START_INDEX + COUNT - 1)).log"
: > "$LOG_FILE"

log() {
  printf '%s\n' "$*" | tee -a "$LOG_FILE"
}

cluster_for_diver() {
  case $(( ($1 - 1) % 4 )) in
    0) printf 'koh_tao' ;;
    1) printf 'bonaire' ;;
    2) printf 'malapascua' ;;
    3) printf 'cozumel' ;;
  esac
}

center_for_cluster() {
  case "$1" in
    koh_tao) printf 'Black Turtle Dive' ;;
    bonaire) printf 'Dive Friends Bonaire' ;;
    malapascua) printf 'Thresher Shark Divers' ;;
    cozumel) printf 'Cozumel Dive School' ;;
  esac
}

site_record() {
  local cluster="$1"
  local slot="$2"
  case "$cluster:$slot" in
    koh_tao:0) printf 'Chumphon Pinnacle|Koh Tao|10.1364334|99.8137469|Barracuda,Whale Shark,Batfish,Grouper' ;;
    koh_tao:1) printf 'White Rock|Koh Tao|10.109502|99.8135659|Hawksbill Turtle,Moray Eel,Clownfish,Triggerfish' ;;
    koh_tao:2) printf 'Twins|Koh Tao|10.1159286|99.8120026|Butterflyfish,Grouper,Sea Turtle,Wrasse' ;;
    bonaire:0) printf 'Bari Reef|Bonaire|12.1674719|-68.2872007|Sea Turtle,Parrotfish,Angelfish,Tarpon' ;;
    bonaire:1) printf 'Hilma Hooker|Bonaire|12.1037524|-68.2901176|Barracuda,Tarpon,Moray Eel,Coral' ;;
    bonaire:2) printf 'Invisibles|Bonaire|12.077631|-68.2801815|Sea Turtle,Spotted Eagle Ray,Parrotfish' ;;
    malapascua:0) printf 'Monad Shoal|Philippines Malapascua|11.3133913|124.1947241|Thresher Shark,Devil Ray,Trevally' ;;
    malapascua:1) printf 'Dakit-Dakit|Philippines Malapascua|11.3235603|124.1090875|Nudibranch,Frogfish,Pipefish' ;;
    malapascua:2) printf 'Lapus-Lapus|Philippines Malapascua|11.3461986|124.1024056|Lionfish,Scorpionfish,Sea Turtle' ;;
    cozumel:0) printf 'Paradise Reef - Cozumel|Mexico|20.4719|-86.9812|Hawksbill Turtle,Angelfish,Parrotfish' ;;
    cozumel:1) printf 'Barracuda - Cozumel|Mexico|20.5702|-86.9186|Barracuda,Eagle Ray,Reef Shark' ;;
    cozumel:2) printf 'Yucab reef|Mexico|20.4152|-87.0087|Hawksbill Turtle,Lobster,Grunts' ;;
  esac
}

site_slot_for_dive() {
  case "$1" in
    1|2|6|9) printf '0' ;;
    3|5|10) printf '1' ;;
    4|7|8) printf '2' ;;
  esac
}

days_ago_for_dive() {
  case "$1" in
    1|2) printf '1' ;;
    3|4) printf '2' ;;
    5|6) printf '3' ;;
    7|8) printf '4' ;;
    9|10) printf '5' ;;
  esac
}

json_species() {
  local csv="$1"
  local out="["
  local first=1
  local old_ifs="$IFS"
  IFS=','
  for item in $csv; do
    item="${item#"${item%%[![:space:]]*}"}"
    item="${item%"${item##*[![:space:]]}"}"
    if [ "$first" -eq 0 ]; then
      out+=","
    fi
    out+="\"$item\""
    first=0
  done
  IFS="$old_ifs"
  out+="]"
  printf '%s' "$out"
}

post_dive() {
  local jar="$1" diver="$2" dive_no="$3" cluster="$4" username="$5"
  local slot record site country lat lon species_csv species_json
  slot="$(site_slot_for_dive "$dive_no")"
  record="$(site_record "$cluster" "$slot")"
  IFS='|' read -r site country lat lon species_csv <<< "$record"
  species_json="$(json_species "$species_csv")"

  local days_ago dive_date
  days_ago="$(days_ago_for_dive "$dive_no")"
  dive_date="$(date -v-"${days_ago}"d +%F)"

  local depth=$(( 35 + ((diver * 7 + dive_no * 11) % 70) ))
  local duration=$(( 42 + ((diver * 5 + dive_no * 7) % 39) ))
  local visibility=$(( 35 + ((diver * 3 + dive_no * 13) % 55) ))
  local air_temp=$(( 80 + ((diver + dive_no) % 8) ))
  local water_temp=$(( 77 + ((diver * 2 + dive_no) % 7) ))
  local weight=$(( 6 + ((diver + dive_no) % 8) ))
  local exposure="3mm"
  local dive_type="reef"
  local current="drift"
  local current_strength="light"

  if [ "$cluster" = "koh_tao" ]; then exposure="shorty"; fi
  if [ "$cluster" = "bonaire" ]; then current="surge"; fi
  if [ "$cluster" = "malapascua" ]; then dive_type="deep"; current="tidal"; current_strength="moderate"; fi
  if [ "$cluster" = "cozumel" ]; then current_strength="moderate"; fi
  if [ "$site" = "Hilma Hooker" ]; then dive_type="wreck"; fi

  local center
  center="$(center_for_cluster "$cluster")"
  if [ $((diver % 5)) -eq 0 ]; then
    center=""
  fi

  local notes
  notes="${username} load-test dive at ${site}. Repeat schedule includes paired dives and return visits; ${visibility} ft viz, ${water_temp} degree water, ${current_strength} ${current}; wildlife: ${species_csv}."

  local curl_args=(
    -sS
    -b "$jar"
    -c "$jar"
    -o /dev/null
    -w "%{http_code}"
    -X POST
    "$BASE_URL/dive/new"
    --form-string "date=$dive_date"
    --form-string "site_name=$site"
    --form-string "dive_site_id="
    --form-string "dive_center_name=$center"
    --form-string "dive_center_id="
    --form-string "country_or_area=$country"
    --form-string "latitude=$lat"
    --form-string "longitude=$lon"
    --form-string "depth_ft=$depth"
    --form-string "duration_min=$duration"
    --form-string "weight_lbs=$weight"
    --form-string "exposure=$exposure"
    --form-string "visibility_ft=$visibility"
    --form-string "air_temp_degrees=$air_temp"
    --form-string "water_temp_degrees=$water_temp"
    --form-string "dive_type=$dive_type"
    --form-string "current=$current"
    --form-string "current_strength=$current_strength"
    --form-string "species_json=$species_json"
    --form-string "notes=$notes"
  )
  if [ $(((diver + dive_no) % 4)) -eq 0 ] && [ -f "$PHOTO_FILE" ]; then
    curl_args+=(-F "photos=@${PHOTO_FILE};type=image/png")
  fi

  local code
  code="$(curl "${curl_args[@]}")"
  if [ "$code" = "302" ]; then
    log "OK dive user=$username dive=$dive_no site=$site date=$dive_date photo=$([ $(((diver + dive_no) % 4)) -eq 0 ] && echo yes || echo no)"
    return 0
  fi
  log "FAIL dive user=$username dive=$dive_no http=$code site=$site"
  return 1
}

short_run="${RUN_ID: -6}"
accounts_ok=0
dives_ok=0
dives_fail=0

for ((diver = START_INDEX; diver < START_INDEX + COUNT; diver++)); do
  username="p${short_run}_${diver}"
  password="DiveLoad-${RUN_ID}-${diver}!"
  cluster="$(cluster_for_diver "$diver")"
  jar="$(mktemp "${TMPDIR:-/tmp}/pelagia_cookie.XXXXXX")"

  signup_code="$(curl -sS -c "$jar" -b "$jar" -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/signup" \
    --form-string "username=$username" \
    --form-string "password=$password")"

  if [ "$signup_code" != "302" ]; then
    login_code="$(curl -sS -c "$jar" -b "$jar" -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/login" \
      --form-string "username=$username" \
      --form-string "password=$password")"
    if [ "$login_code" != "302" ]; then
      log "FAIL account user=$username signup_http=$signup_code login_http=$login_code"
      rm -f "$jar"
      continue
    fi
    log "OK account user=$username reused=true cluster=$cluster"
  else
    log "OK account user=$username reused=false cluster=$cluster"
  fi
  accounts_ok=$((accounts_ok + 1))

  for dive_no in {1..10}; do
    if post_dive "$jar" "$diver" "$dive_no" "$cluster" "$username"; then
      dives_ok=$((dives_ok + 1))
    else
      dives_fail=$((dives_fail + 1))
    fi
  done
  rm -f "$jar"
done

log "SUMMARY run_id=$RUN_ID start=$START_INDEX count=$COUNT accounts_ok=$accounts_ok dives_ok=$dives_ok dives_fail=$dives_fail"
