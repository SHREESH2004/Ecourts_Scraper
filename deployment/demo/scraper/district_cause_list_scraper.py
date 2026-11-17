"""Interactive scraper for district-court Civil and Criminal cause lists."""

import os
import tempfile
import urllib.parse
import webbrowser
from datetime import datetime
from html.parser import HTMLParser

import requests


DISTRICT_PORTAL_ORIGIN = "https://services.ecourts.gov.in"
DISTRICT_PORTAL_BASE = f"{DISTRICT_PORTAL_ORIGIN}/ecourtindia_v6/"
DISTRICT_CAUSE_LIST_URL = f"{DISTRICT_PORTAL_BASE}?p=cause_list/index"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    )
}


def clean_dir_name(name):
    """Clean a string to be used as a directory name."""
    cleaned = "".join(c if c.isalnum() or c in " -" else "_" for c in name or "")
    cleaned = cleaned.replace(" ", "_").replace("-", "_")
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "unknown"


class DistrictPageParser(HTMLParser):
    """Read select options, hidden form values, and CAPTCHA image paths."""

    def __init__(self, select_id=None):
        super().__init__()
        self.select_id = select_id
        self._in_target_select = False
        self._option_value = None
        self._option_text = []
        self.options = []
        self.inputs = {}
        self.images = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "select":
            self._in_target_select = (
                self.select_id is None or attributes.get("id") == self.select_id
            )
        elif tag == "option" and (self._in_target_select or self.select_id is None):
            self._option_value = attributes.get("value", "")
            self._option_text = []
        elif tag == "input":
            name = attributes.get("name")
            if name:
                self.inputs[name] = attributes.get("value", "")
        elif tag == "img":
            src = attributes.get("src")
            if src:
                self.images.append((attributes.get("id", ""), src))

    def handle_data(self, data):
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag):
        if tag == "option" and self._option_value is not None:
            text = " ".join("".join(self._option_text).split())
            self.options.append((self._option_value, text))
            self._option_value = None
            self._option_text = []
        elif tag == "select":
            self._in_target_select = False


class DistrictTextParser(HTMLParser):
    """Extract readable text from HTML."""

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def parse_options(markup, select_id):
    parser = DistrictPageParser(select_id)
    parser.feed(markup)
    if not parser.options and "<select" not in markup.lower():
        parser = DistrictPageParser()
        parser.feed(markup)
    return parser.options


def select_option(label, options):
    choices = [(value, name) for value, name in options if value and name]
    if not choices:
        raise RuntimeError(f"The eCourts portal returned no choices for {label}.")

    print(f"\nAvailable {label}:")
    for index, (_, name) in enumerate(choices, 1):
        print(f"  {index}. {name}")

    while True:
        answer = input(f"Choose {label} by number: ").strip()
        try:
            selected_index = int(answer) - 1
        except ValueError:
            selected_index = -1
        if 0 <= selected_index < len(choices):
            return choices[selected_index]
        print(f"Enter a number from 1 to {len(choices)}.")


def error_message(markup):
    parser = DistrictTextParser()
    parser.feed(markup or "")
    return " ".join(parser.parts)


def require_success(result, action):
    if str(result.get("status")) != "1":
        detail = error_message(result.get("errormsg", ""))
        suffix = f": {detail}" if detail else "."
        raise RuntimeError(f"The eCourts portal could not {action}{suffix}")


def ajax(session, token, route, payload):
    """Submit one portal AJAX request and return its JSON and rotated token."""
    response = session.post(
        f"{DISTRICT_PORTAL_BASE}?p={route}",
        data={**payload, "ajax_req": "true", "app_token": token},
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "delimeter": "mbnbre54",
            "Jfjtrrt46": "mbnbre54",
            "Referer": f"{DISTRICT_PORTAL_ORIGIN}/",
        },
        timeout=30,
    )
    response.raise_for_status()
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"The eCourts portal returned an unexpected response for {route}."
        ) from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"The eCourts portal returned invalid data for {route}.")
    if result.get("errormsg"):
        detail = error_message(result["errormsg"])
        raise RuntimeError(f"The eCourts portal rejected {route}: {detail}")
    return result, result.get("app_token") or token


def open_captcha(session, token):
    """Open a CAPTCHA image from this session for the user to solve manually."""
    result, token = ajax(session, token, "casestatus/getCaptcha", {})
    parser = DistrictPageParser()
    parser.feed(result.get("div_captcha", ""))
    image_sources = [src for image_id, src in parser.images if image_id == "captcha_image"]
    if not image_sources:
        image_sources = [src for _, src in parser.images]
    if not image_sources:
        raise RuntimeError("The eCourts portal did not provide a CAPTCHA image.")

    image_response = session.get(
        urllib.parse.urljoin(DISTRICT_PORTAL_BASE, image_sources[0]),
        headers={"Referer": DISTRICT_CAUSE_LIST_URL},
        timeout=20,
    )
    image_response.raise_for_status()
    content_type = image_response.headers.get("Content-Type", "").lower()
    extension = ".gif" if "gif" in content_type else ".jpg" if "jpeg" in content_type else ".png"
    image_file = tempfile.NamedTemporaryFile(
        prefix="ecourts_captcha_", suffix=extension, delete=False
    )
    try:
        image_file.write(image_response.content)
        image_file.close()
        image_path = os.path.abspath(image_file.name)
        print(f"\nCAPTCHA image: {image_path}")
        webbrowser.open("file:///" + image_path.replace("\\", "/"))
        captcha_answer = input("Enter the CAPTCHA shown in the image: ").strip()
    finally:
        if not image_file.closed:
            image_file.close()
        try:
            os.unlink(image_file.name)
        except OSError:
            pass
    if not captcha_answer:
        raise ValueError("A CAPTCHA answer is required to request the cause list.")
    return captcha_answer, token


def scrape_district_cause_list():
    """Select and save one District Court Civil or Criminal cause list."""
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        page = session.get(DISTRICT_CAUSE_LIST_URL, timeout=30)
        page.raise_for_status()
        page_parser = DistrictPageParser()
        page_parser.feed(page.text)
        token = page_parser.inputs.get("app_token")
        if not token:
            token = urllib.parse.parse_qs(
                urllib.parse.urlparse(page.url).query
            ).get("app_token", [None])[0]
        if not token:
            raise RuntimeError("Could not obtain an eCourts session token.")

        state_code, state_name = select_option(
            "state", parse_options(page.text, "sess_state_code")
        )
        districts_result, token = ajax(
            session, token, "casestatus/fillDistrict", {"state_code": state_code}
        )
        require_success(districts_result, "load districts for that state")
        district_code, district_name = select_option(
            "district",
            parse_options(districts_result.get("dist_list", ""), "sess_dist_code"),
        )

        complexes_result, token = ajax(
            session,
            token,
            "casestatus/fillcomplex",
            {"state_code": state_code, "dist_code": district_code},
        )
        require_success(complexes_result, "load court complexes")
        complex_value, complex_name = select_option(
            "court complex",
            parse_options(complexes_result.get("complex_list", ""), "court_complex_code"),
        )
        complex_parts = complex_value.split("@")
        if len(complex_parts) < 3:
            raise RuntimeError("The eCourts portal returned an invalid court-complex selection.")
        complex_code, establishment_code, establishment_required = complex_parts[:3]

        if establishment_required == "Y":
            establishments_result, token = ajax(
                session,
                token,
                "casestatus/fillCourtEstablishment",
                {
                    "state_code": state_code,
                    "dist_code": district_code,
                    "court_complex_code": complex_code,
                },
            )
            require_success(establishments_result, "load establishments")
            establishment_code, _ = select_option(
                "establishment",
                parse_options(
                    establishments_result.get("establishment_list", ""),
                    "court_est_code",
                ),
            )

        court_result, token = ajax(
            session,
            token,
            "cause_list/fillCauseList",
            {
                "state_code": state_code,
                "dist_code": district_code,
                "court_complex_code": complex_code,
                "est_code": establishment_code,
                "search_act": "",
            },
        )
        require_success(court_result, "load courts for this complex")
        court_value, court_name = select_option(
            "court name",
            parse_options(court_result.get("cause_list", ""), "CL_court_no"),
        )

        default_date = datetime.today().strftime("%d-%m-%Y")
        date_text = input(f"Cause-list date (DD-MM-YYYY) [{default_date}]: ").strip()
        date_text = date_text or default_date
        try:
            cause_date = datetime.strptime(date_text, "%d-%m-%Y").date()
        except ValueError as exc:
            raise ValueError("Date must be in DD-MM-YYYY format.") from exc

        print("\nCause-list type:")
        print("  1. Civil")
        print("  2. Criminal")
        type_choice = input("Choose cause-list type: ").strip()
        if type_choice not in {"1", "2"}:
            raise ValueError("Choose 1 for Civil or 2 for Criminal.")
        cause_type, cause_type_code = (
            ("Civil", "civ") if type_choice == "1" else ("Criminal", "cri")
        )

        print(
            f"\nSelected: {state_name} / {district_name} / {complex_name} / "
            f"{court_name} / {cause_type} / {cause_date:%d-%m-%Y}"
        )
        if input("Scrape this cause list? [y/N]: ").strip().casefold() not in {"y", "yes"}:
            print("Scrape cancelled.")
            return

        for attempt in range(3):
            captcha_answer, token = open_captcha(session, token)
            submit_result, token = ajax(
                session,
                token,
                "cause_list/submitCauseList",
                {
                    "CL_court_no": court_value,
                    "causelist_date": cause_date.strftime("%d-%m-%Y"),
                    "cause_list_captcha_code": captcha_answer,
                    "court_name_txt": court_name,
                    "state_code": state_code,
                    "dist_code": district_code,
                    "court_complex_code": complex_code,
                    "est_code": establishment_code,
                    "cicri": cause_type_code,
                    "selprevdays": "1" if cause_date < datetime.today().date() else "0",
                },
            )
            if str(submit_result.get("status")) == "1":
                break
            if attempt < 2:
                print("The portal did not accept that CAPTCHA; please try the refreshed image.")
        else:
            raise RuntimeError("The eCourts portal rejected the CAPTCHA three times.")

        cause_list_html = submit_result.get("case_data", "")
        if not cause_list_html:
            print("The portal accepted the request but returned no cause-list entries.")
            return

        save_dir = os.path.join(
            "district_cause_lists",
            clean_dir_name(state_name),
            clean_dir_name(district_name),
            clean_dir_name(complex_name),
        )
        os.makedirs(save_dir, exist_ok=True)
        output_path = os.path.join(
            save_dir,
            f"{cause_date:%Y%m%d}_{cause_type.lower()}_{clean_dir_name(court_name)}.html",
        )
        with open(output_path, "w", encoding="utf-8") as output_file:
            output_file.write(cause_list_html)

        text_parser = DistrictTextParser()
        text_parser.feed(cause_list_html)
        print(f"\nCause list saved to: {os.path.abspath(output_path)}")
        print("\nCause-list preview:")
        print(" ".join(text_parser.parts)[:4000] or "(No readable text in the response.)")
    finally:
        session.close()


if __name__ == "__main__":
    try:
        scrape_district_cause_list()
    except Exception as exc:
        print(f"District-court scrape failed: {exc}")
        raise
