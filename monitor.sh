#!/usr/bin/env bash

# 修复 Windows 下 HOME 目录识别问题
export HOME="${USERPROFILE:-${HOME:-/f}}"
export USERPROFILE="${USERPROFILE:-$HOME}"
export HOMEDRIVE="${HOMEDRIVE:-F:}"
export HOMEPATH="${HOMEPATH:-/}"

# easy-tdx 专用配置目录
export EASY_TDX_CONFIG_DIR="$HOME/.easy_tdx"

export TDX_HOME="/f/new_tdx"
# easy-tdx screen intraday --period 5MIN --lookback 6 --min-pct 2.0 --table

for block in "强势" "稳健"
do
    easy-tdx screen monitor \
      --block-dir "$TDX_HOME/T0002/blocknew" \
      --from-block "$block" \
      --period 1MIN \
      --lookback 10 \
      --min-pct 0.3 \
      --volume-ratio 1.2 \
      --workers 8 \
      --to-block "${block}异动" \
      --table
done