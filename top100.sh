export TDX_HOME="/f/new_tdx"
# --universe` | `all`（默认）/ `sh` / `sz` / 文件路径
# | `--preset` | 预设模式：`steady`（默认）/ `breakout` / `balanced` |
# | `--min-listed-days` | 最小上市天数（默认 65，保证能算 60 日涨幅） |

# easy-tdx screen strength --universe sz --preset breakout  --top 50 --min-amount 1000000000 --workers 8 --table --names --output sz_strength_20260706_breakout.json
easy-tdx screen strength --universe all --preset steady  --top 100 --min-amount 1000000000 --workers 8 --table --names --to-block 稳健 --block-dir "$TDX_HOME/T0002/blocknew"
easy-tdx screen strength --universe all --preset breakout  --top 100 --min-amount 1000000000 --workers 8 --table --names --to-block 强势 --block-dir "$TDX_HOME/T0002/blocknew"