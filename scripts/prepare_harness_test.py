"""Copy an untouched local test set and export the same small task selection for any harness."""
import argparse
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proofparse.review.review import export_worklist

CASES = [
    "bioinspired_microrobots::visual_review/0",
    "blade_instability::visual_review/0",
    "blade_instability::formula_check/display/0",
    "robotics_software::visual_review/18",
    "robotics_software::visual_review/21",
    "slam_part1::visual_review/8",
    "robotics_software::page_review/16",
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("baseline",type=Path)
    p.add_argument("destination",type=Path)
    args=p.parse_args()
    if args.destination.exists(): p.error("Destination exists; use a new directory to keep runs independent")
    shutil.copytree(args.baseline,args.destination)
    export_worklist(args.destination,args.destination/'review_worklist.json')
    data=json.loads((args.destination/'review_worklist.json').read_text(encoding='utf-8'))
    data['items']=[x for x in data['items'] if x['uid'] in CASES]
    if len(data['items']) != len(CASES): raise ValueError('Baseline does not contain the expected test cases')
    (args.destination/'harness_cases.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Prepared {len(CASES)} tasks in {args.destination/'harness_cases.json'}")


if __name__ == '__main__': main()
