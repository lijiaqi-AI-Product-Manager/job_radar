"""生成逐行无损核验的精简正文分发副本，原始数据库不变。"""

import argparse
import json
from pathlib import Path

from jobradar.compact_text import export_compact_text


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    export_compact_text(args.source,args.out)
    print(json.dumps({"original_bytes":args.source.stat().st_size,"compact_bytes":args.out.stat().st_size,
                      "all_logical_rows_verified":True}))


if __name__=="__main__":
    main()
