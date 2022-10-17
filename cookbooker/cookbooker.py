from __future__ import annotations
from ast import Expression
from email.mime import base
from urllib.request import urlopen
from urllib.error import HTTPError
from os import getcwd, mkdir, PathLike, listdir
from os.path import join, exists
from shutil import rmtree
from multiprocessing.pool import ThreadPool as Pool
from typing import Tuple, Union, List
from sys import argv
import argparse
import re
import img2pdf
import ocrmypdf
from enum import Enum, auto
from warnings import warn
from time import sleep
from random import randint


def main(arguments: list) -> None:
    args = parse_arguments(arguments)
    if args.interactive:
        args = interactive_parsing(args)
    if (not args.url or not args.pages) and args.download:
        print("URL and Pages required for downloading, entering interactive parsing.")
        args = interactive_parsing(args)
        if not args.url or not args.pages:
            print("Still missing URL or Pages, exiting...")
            return None
    here = getcwd()
    img_dir = join(here, "tmp")
    pdf_dif = join(here, "pdf")
    pdf_name = f"{args.title} - {args.author}.pdf"  # default name

    if args.download:
        if exists(img_dir):
            rmtree(img_dir)
        mkdir(img_dir)
        if "babel.hathitrust.org" in args.url:
            download_images(
                base_url=args.url,
                npages=args.pages,
                directory=img_dir,
                site=Site.BABLE,
            )
        else:
            print("Not a recognized URL, exiting...")
            return None
    if args.pdf:
        if not exists(pdf_dif):
            mkdir(pdf_dif)
        pdf_name = make_pdf(
            image_directory=img_dir,
            pdf_directory=pdf_dif,
            author=args.author,
            title=args.title,
        )
    if args.ocr:
        ocr_pdf(directory=pdf_dif, pdf_file=pdf_name)


class Site(Enum):
    BABLE = auto()


def parse_arguments(args: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-u", "--url", help="url", default="", type=str, dest="url")
    parser.add_argument(
        "-n",
        "--pages",
        help="number of pages",
        default=0,
        type=int,
        dest="pages",
    )
    parser.add_argument(
        "-a",
        "--author",
        help="name of author",
        default="",
        type=str,
        dest="author",
    )
    parser.add_argument(
        "-t",
        "--title",
        help="title of book",
        default="",
        type=str,
        dest="title",
    )
    parser.add_argument(
        "-d",
        "--nodownload",
        help="Don't download images.  Will use existing downloaded images.",
        default=True,
        action="store_false",
        dest="download",
    )
    parser.add_argument(
        "-p",
        "--pdf",
        help="Make pdf?",
        default=False,
        action="store_true",
        dest="pdf",
    )
    parser.add_argument(
        "-o",
        "--ocr",
        help="OCR document?",
        default=False,
        action="store_true",
        dest="ocr",
    )
    parser.add_argument(
        "-i",
        "--interactive",
        help="Interactive argument parsing",
        default=False,
        action="store_true",
        dest="interactive",
    )
    return parser.parse_args(args)


def interactive_parsing(args: argparse.Namespace) -> argparse.Namespace:
    for argument in vars(args):
        if argument == "interactive":
            continue  # don't need to re-parse the interactive argument
        new_argument = input(f"{argument:<15} {args.__getattribute__(argument)}: ")
        if new_argument:
            if isinstance(args.__getattribute__(argument), int) and not isinstance(
                args.__getattribute__(argument), bool
            ):
                args.__setattr__(argument, int(new_argument))
            elif isinstance(args.__getattribute__(argument), list):
                args.__setattr__(argument, [int(x) for x in new_argument.split(" ")])
            elif isinstance(args.__getattribute__(argument), bool):
                if new_argument.lower() in ("t", "true"):
                    args.__setattr__(argument, True)
                else:
                    args.__setattr__(argument, False)
            elif isinstance(args.__getattribute__(argument), str):
                args.__setattr__(argument, new_argument)
    return args


def download_images(
    base_url: str,
    npages: int,
    directory: Union[str, bytes, PathLike],
    site: Site,
) -> None:
    # https://babel.hathitrust.org/cgi/imgsrv/image?id=coo.31924000478770;seq=1;size=125;rotation=0
    expression, replacement = get_url_replacements(base_url=base_url, site=site)
    url_info = []
    for i in range(1, npages + 1):
        url_info.append((i, expression.sub(f"{replacement}{i}", base_url)))
    pool = Pool(10)
    for image_data in pool.imap_unordered(fetch_image, url_info):
        page_number = image_data[0]
        image = image_data[1]
        starting_bytes = image[:16].hex()
        image_type = determine_filetype(starting_bytes=starting_bytes)
        if not image_type:
            warn(f"could not determine file type for {page_number=}, {starting_bytes=}")
        image_file = join(directory, f"{page_number}{image_type}")
        with open(image_file, "wb") as file:
            file.write(image)
    return None


def get_url_replacements(base_url: str, site: str):
    if site == Site.BABLE:
        expression = expression = re.compile(r"seq=\d+")
        replacement = "seq="
        return expression, replacement


def fetch_image(url_info: Tuple[int, str]) -> Tuple[int, bytes]:
    page = url_info[0]
    url = url_info[1]
    for i in range(10):
        try:
            with urlopen(url=url) as site:
                print(f"fetching url {url}")
                return page, site.read()
        except HTTPError as e:
            sleep_time = randint(0, (2**i) - 1)
            print(f"encountered {e} on attempt {i} for page {page}, sleeping {sleep_time} second(s)...")
            sleep(sleep_time)


def determine_filetype(starting_bytes: str) -> str:
    sigs = {
        ".gif": ["474946383761", "474946383961"],
        ".png": ["89504E470D0A1A0A"],
        ".jpg": ["FFD8FFDB", "FFD8FFE000104A4649460001"],
    }
    for ext, sigs in sigs.items():
        for sig in sigs:
            if sig == starting_bytes[: len(sig)].upper():
                return ext
    return ""


def make_pdf(
    image_directory: Union[str, bytes, PathLike],
    pdf_directory: Union[str, bytes, PathLike],
    author: str,
    title: str,
) -> str:
    image_files = find_images(directory=image_directory)
    pdf_name = f"{title} - {author}.pdf"
    letter = (img2pdf.in_to_pt(8.5), img2pdf.in_to_pt(11))
    layout_fun = img2pdf.get_layout_fun(letter)
    with open(join(pdf_directory, pdf_name), "wb") as file:
        print(f"creating {pdf_name}")
        file.write(img2pdf.convert(image_files, author=author, title=title, layout_fun=layout_fun))
    return pdf_name


def find_images(directory: Union[str, bytes, PathLike]) -> List[str]:
    files = listdir(directory)
    images = filter(is_image, files)
    images = [join(directory, image) for image in sorted(images, key=lambda x: int(x.split(".")[0]))]
    return images


def is_image(filename: str) -> bool:
    image_types = ("jpg", "png", "gif")
    if filename.split(".")[-1] in image_types:
        return True
    return False


def ocr_pdf(directory: Union[str, bytes, PathLike], pdf_file):
    input_file = join(directory, pdf_file)
    output_file = join(directory, f"[OCR] {pdf_file}")
    ocrmypdf.ocr(input_file=input_file, output_file=output_file)


if __name__ == "__main__":
    main(argv[1:])
    # for testing
    # main(
    #     [
    #         "-u",
    #         "https://babel.hathitrust.org/cgi/imgsrv/image?id=loc.ark:/13960/t2s47dp7t;seq=7;size=125;rotation=0",
    #         "-a",
    #         "Thomas M. Hilliard",
    #         "-n",
    #         "60",
    #         "-t",
    #         "The Art of Carving",
    #         "-d",
    #         "-o",
    #         "-p",
    #     ]
    # )
