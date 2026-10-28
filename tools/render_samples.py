"""Render local gold samples without Gemini or network access."""
import argparse
from app.schemas.profile import ShopProfile
from app.services.renderer import render_ad_card, render_menu_board
from eval.common import ROOT, read_rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ids', required=True)
    parser.add_argument('--headline', default='오늘 저녁, 함께 나누는 한 접시')
    parser.add_argument('--kind', choices=('ad_card', 'menu_board'), default='ad_card')
    parser.add_argument('--suffix', default='')
    args = parser.parse_args(argv)
    rows = read_rows(ROOT / 'data/samples/answer_profiles_gold.jsonl')
    output = ROOT / 'data/render_runs'
    output.mkdir(parents=True, exist_ok=True)
    for row_id in map(int, args.ids.split(',')):
        profile = ShopProfile.model_validate(rows[row_id]['profile'])
        if not profile.menus:
            raise ValueError(f'ID {row_id}: 메뉴를 입력해 주세요')
        result = render_menu_board(profile) if args.kind == 'menu_board' else render_ad_card(profile, profile.menus[0], {'headline': args.headline, 'body': '편하게 만나보세요.'})
        path = output / f'{args.kind}_{row_id}{args.suffix}.png'
        path.write_bytes(result.png)
        print(f'{path.name}: {result.warnings}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
