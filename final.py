import asyncio
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import StaleElementReferenceException, WebDriverException
from bs4 import BeautifulSoup
from telegram import Bot
import traceback

TOKEN = "8035287994:AAEEWPvDYpCxXBUKTTvEBNfxZtZkdlZg4pM"
CHAT_ID = 7509164117

SCRAPE_INTERVAL = 30  # seconds

sent_message_ids = {}           # match_key -> message_id
last_sent_message_text = {}     # match_key -> last sent text
last_known_match_data = {}

async def send_telegram_message(bot, text):
    msg = await bot.send_message(chat_id=CHAT_ID, text=text)
    return msg.message_id

async def edit_telegram_message(bot, message_id, text):
    try:
        await bot.edit_message_text(chat_id=CHAT_ID, message_id=message_id, text=text)
    except Exception as e:
        print(f"Failed to edit message: {e}")

def extract_cards_and_name(td):
    html = td.get_attribute('innerHTML')
    soup = BeautifulSoup(html, 'html.parser')
    red, yellow = 0, 0
    for span in soup.find_all('span'):
        if 'redcard' in span.get('class', []):
            try:
                red += int(span.text.strip())
            except:
                pass
        if 'yellowcard' in span.get('class', []):
            try:
                yellow += int(span.text.strip())
            except:
                pass
    for span in soup.find_all('span'):
        span.decompose()
    team_name = soup.get_text().strip()
    return team_name, red, yellow

def extract_minute(cell_text):
    cell_text = cell_text.strip().replace('\n', ' ').replace('\r', '')
    if cell_text.endswith("'") or cell_text.endswith("'+"):
        return cell_text
    if "-" in cell_text and ":" in cell_text:
        return "ENDTIME"
    return cell_text

def float_or_none(x):
    try:
        return float(str(x).replace("+", "").replace("−", "-").replace("–", "-"))
    except (ValueError, TypeError):
        return None

def scrape_tablematch1(driver):
    table = driver.find_element(By.ID, "tablematch1")
    rows = table.find_elements(By.TAG_NAME, "tr")
    matches = []
    league = ""
    i = 0
    while i < len(rows):
        tds = rows[i].find_elements(By.TAG_NAME, "td")
        if len(tds) == 1 and tds[0].get_attribute("colspan"):
            text = tds[0].text.strip()
            if text:
                league = text
            i += 1
            continue
        if len(tds) > 1 and tds[0].text.strip() == "H":
            home_team_td = tds[1]
            home_team, home_red, home_yellow = extract_cards_and_name(home_team_td)
            minute_cell_text = tds[2].text.strip()
            minute = extract_minute(minute_cell_text)
            home_goals = tds[3].text.strip()
            if i + 1 < len(rows):
                away_tds = rows[i + 1].find_elements(By.TAG_NAME, "td")
                if away_tds[0].text.strip() == "A":
                    away_team_td = away_tds[1]
                    away_team, away_red, away_yellow = extract_cards_and_name(away_team_td)
                    away_goals = away_tds[2].text.strip()
                    score = f"{home_goals}-{away_goals}"
                    matches.append({
                        "league": league,
                        "home_team": home_team,
                        "away_team": away_team,
                        "minute": minute,
                        "home_goals": int(home_goals) if home_goals.isdigit() else 0,
                        "away_goals": int(away_goals) if away_goals.isdigit() else 0,
                        "score": score,
                        "home_red_card": home_red,
                        "away_red_card": away_red,
                        "home_yellow_card": home_yellow,
                        "away_yellow_card": away_yellow,
                    })
                    i += 2
                    continue
        i += 1
    return matches

def scrape_tablematch2(driver):
    table = driver.find_element(By.ID, "tablematch2")
    rows = table.find_elements(By.TAG_NAME, "tr")
    matches_data = []
    i = 0
    while i < len(rows):
        tds = rows[i].find_elements(By.TAG_NAME, "td")
        if len(tds) > 1 and tds[0].text.strip() == "H":
            home_data = [td.text.strip() for td in tds]
            if i + 1 < len(rows):
                away_tds = rows[i + 1].find_elements(By.TAG_NAME, "td")
                if away_tds[0].text.strip() == "A":
                    away_data = [td.text.strip() for td in away_tds]
                    match_data = {
                        "home_spread": home_data[1],
                        "home_spread_open": home_data[2],
                        "home_odds1": home_data[4],
                        "home_odds2": home_data[5],
                        "total_line_current": home_data[6],
                        "total_line_open": home_data[7],
                        "away_spread": away_data[1],
                        "away_spread_open": away_data[2],
                        "away_odds1": away_data[4],
                        "away_odds2": away_data[5],
                        "tips": home_data[-1] if "tips" in tds[-1].get_attribute("class") else "",
                    }
                    matches_data.append(match_data)
                    i += 2
                    continue
        i += 1
    return matches_data

def combine_matches(info_list, data_list):
    combined = []
    for info, data in zip(info_list, data_list):
        combined.append({**info, **data})
    return combined

def get_minute_as_int(minute_str):
    if isinstance(minute_str, int):
        return minute_str
    if isinstance(minute_str, str):
        if minute_str.endswith("'"):
            try:
                return int(minute_str.replace("'", "").split('+')[0])
            except ValueError:
                return 0
        if minute_str.endswith("'+"):
            try:
                return int(minute_str.replace("'+", ""))
            except ValueError:
                return 0
        if minute_str == "HT":
            return 45
        if minute_str == "FT":
            return 90
    return 0

def should_alert_canale1(match):
    minute_val = get_minute_as_int(match['minute'])
    if not (58 <= minute_val <= 63):
        return False
    if (match['home_red_card'] == 0 and match['away_red_card'] == 0 and
        (match['home_goals'] + match['away_goals']) <= 1):
        spread_c = float_or_none(match['home_spread'])
        spread_o = float_or_none(match['home_spread_open'])
        ttl_c = float_or_none(match['total_line_current'])
        ttl_o = float_or_none(match['total_line_open'])
        if (spread_c is not None and spread_o is not None and ttl_c is not None and ttl_o is not None):
            return (spread_c != spread_o and ttl_c != ttl_o and ttl_c >= 2.5)
    return False

def should_alert_canale2(match):
    minute_val = get_minute_as_int(match['minute'])
    if not (60 <= minute_val <= 65):
        return False
    if (match['home_red_card'] == 0 and match['away_red_card'] == 0 and
        (match['home_goals'] + match['away_goals']) == 1):
        spread_c = float_or_none(match['home_spread'])
        spread_o = float_or_none(match['home_spread_open'])
        ttl_c = float_or_none(match['total_line_current'])
        if (spread_c is not None and spread_o is not None and ttl_c is not None):
            spread_c_abs = abs(spread_c)
            return (spread_c != spread_o and (spread_c == 0 or spread_c_abs == 0.25) and ttl_c >= 2.5)
    return False

def should_alert_canale3(match):
    minute_val = get_minute_as_int(match['minute'])
    if not (65 <= minute_val <= 70):
        return False
    if (match['home_red_card'] == 0 and match['away_red_card'] == 0 and
        match['score'] in ['0-0', '0-1', '1-0', '1-1']):
        spread_c = float_or_none(match['home_spread'])
        spread_o = float_or_none(match['home_spread_open'])
        ttl_c = float_or_none(match['total_line_current'])
        ttl_o = float_or_none(match['total_line_open'])
        if (spread_c is not None and spread_o is not None and ttl_c is not None and ttl_o is not None):
            spread_c_abs = abs(spread_c)
            return (ttl_c > ttl_o and ttl_c >= 2.75 and spread_c > spread_o and spread_c_abs >= 1.25)
    return False

# --- UPDATED MESSAGE FORMATTING ---

def format_match_message(match):
    msg = f"{match['league']}: {match['home_team']} vs {match['away_team']}\n"
    msg += f"Minute: {match['minute']} | Score: {match['score']}\n"
    msg += f"Red Cards: {match['home_red_card']} (Home), {match['away_red_card']} (Away)\n"
    msg += f"Handicap: {match['home_spread']} / {match['away_spread']}\n"
    msg += f"Odds: {match['home_odds1']}, {match['home_odds2']} / {match['away_odds1']}, {match['away_odds2']}\n"
    msg += f"Total Line: {match['total_line_current']} (cur), {match['total_line_open']} (open)\n"
    if match.get('tips'):
        msg += f"Tips: {match['tips']}\n"
    return msg

def format_final_result_message(match):
    msg = f"{match['league']}: {match['home_team']} vs {match['away_team']}\n"
    msg += f"Minute: Finished. | Score: {match['score']}\n"
    msg += f"Red Cards: {match['home_red_card']} (Home), {match['away_red_card']} (Away)\n"
    msg += f"Handicap: {match['home_spread']} / {match['away_spread']}\n"
    msg += f"Odds: {match['home_odds1']}, {match['home_odds2']} / {match['away_odds1']}, {match['away_odds2']}\n"
    msg += f"Total Line: {match['total_line_current']} (cur), {match['total_line_open']} (open)\n"
    if match.get('tips'):
        msg += f"Tips: {match['tips']}\n"
    return msg

def robust_scrape_tablematch1(driver, max_retries=3):
    for attempt in range(max_retries):
        try:
            return scrape_tablematch1(driver)
        except StaleElementReferenceException:
            print(f"Attempt {attempt+1}/{max_retries}: StaleElementReferenceException in tablematch1, retrying...")
            asyncio.sleep(1)
    print("Failed to scrape tablematch1 after retries.")
    return []

def robust_scrape_tablematch2(driver, max_retries=3):
    for attempt in range(max_retries):
        try:
            return scrape_tablematch2(driver)
        except StaleElementReferenceException:
            print(f"Attempt {attempt+1}/{max_retries}: StaleElementReferenceException in tablematch2, retrying...")
            asyncio.sleep(1)
    print("Failed to scrape tablematch2 after retries.")
    return []

async def main_loop():
    driver = None
    bot = Bot(token=TOKEN)
    try:
        driver = webdriver.Chrome()
        driver.get("https://www.asianbetsoccer.com/livescore.html")
        await asyncio.sleep(5)

        refresh_counter = 0
        while True:
            try:
                info_list = robust_scrape_tablematch1(driver)
                data_list = robust_scrape_tablematch2(driver)
                combined_matches = combine_matches(info_list, data_list)

                current_active_match_keys = set()
                for match in combined_matches:
                    match_key = f"{match['league']}|{match['home_team']}|{match['away_team']}"
                    current_active_match_keys.add(match_key)
                    last_known_match_data[match_key] = match

                    # Only send message when a condition is met, and track message_id and last text
                    if match_key not in sent_message_ids:
                        if should_alert_canale1(match) or should_alert_canale2(match) or should_alert_canale3(match):
                            message = format_match_message(match)
                            msg_id = await send_telegram_message(bot, message)
                            sent_message_ids[match_key] = msg_id
                            last_sent_message_text[match_key] = message

                    # If message was already sent and match is finished, edit it with the final result
                    if match_key in sent_message_ids and match['minute'] == "ENDTIME":
                        final_message = format_final_result_message(match)
                        if last_sent_message_text.get(match_key) != final_message:
                            await edit_telegram_message(bot, sent_message_ids[match_key], final_message)
                            last_sent_message_text[match_key] = final_message

                # Clean up matches that are no longer present (optional, for memory)
                keys_to_remove = []
                for stored_match_key in last_known_match_data.keys():
                    if stored_match_key not in current_active_match_keys:
                        keys_to_remove.append(stored_match_key)
                for key in keys_to_remove:
                    del last_known_match_data[key]

                refresh_counter += 1
                if refresh_counter % 20 == 0:
                    print("Refreshing browser to avoid potential issues.")
                    driver.refresh()
                    await asyncio.sleep(3)

                await asyncio.sleep(SCRAPE_INTERVAL)

            except StaleElementReferenceException:
                print("StaleElementReferenceException caught. Retrying full scrape after short delay...")
                await asyncio.sleep(2)
            except WebDriverException as e:
                print(f"WebDriverException caught: {e}. Attempting to restart browser...")
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                driver = webdriver.Chrome()
                driver.get("https://www.asianbetsoccer.com/livescore.html")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"An unexpected error occurred: {e}")
                traceback.print_exc()
                await asyncio.sleep(5)
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    asyncio.run(main_loop())