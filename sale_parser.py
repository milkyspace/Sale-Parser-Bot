import re
import os
import html
import json
import time
import random
import requests
import urllib.parse
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
import datetime

# Конфигурация
TELEGRAM_BOT_TOKEN = '***'
TELEGRAM_CHANNEL_ID = '@'***'
SENT_DEALS_FILE = 'sent_deals.json'
PEPPER_URL = 'https://www.pepper.ru/new'
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36'
]
CLEAN_INTERVAL_DAYS = 2  # Интервал очистки истории в днях

def setup_driver():
    """Настройка Selenium WebDriver с расширенными опциями для обхода блокировок"""
    chrome_options = Options()

    # Расширенные опции для обхода защиты
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("start-maximized")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--allow-running-insecure-content")
    chrome_options.add_argument("--ignore-certificate-errors")
    chrome_options.add_argument(f"user-agent={random.choice(USER_AGENTS)}")

    # Экспериментальные опции
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Инициализация драйвера
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    # Применение stealth-режима
    stealth(driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )

    # Скрытие автоматизации
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_cdp_cmd('Network.setUserAgentOverride', {
        "userAgent": random.choice(USER_AGENTS)
    })

    return driver


def load_sent_deals():
    """Загрузка отправленных сделок и времени последней очистки"""
    if os.path.exists(SENT_DEALS_FILE):
        try:
            with open(SENT_DEALS_FILE, 'r') as f:
                data = json.load(f)
                # Проверка структуры файла
                if isinstance(data, dict) and 'deals' in data and 'last_clean' in data:
                    return data
        except:
            pass

    # Возвращаем структуру по умолчанию
    return {
        'deals': [],
        'last_clean': datetime.datetime.now().isoformat()
    }


def save_sent_deals(data):
    """Сохранение данных о сделках и времени очистки"""
    with open(SENT_DEALS_FILE, 'w') as f:
        json.dump(data, f)


def should_clean_history(data):
    """Проверка необходимости очистки истории"""
    last_clean = datetime.datetime.fromisoformat(data['last_clean'])
    now = datetime.datetime.now()
    return (now - last_clean).days >= CLEAN_INTERVAL_DAYS


def clean_history(data):
    """Очистка истории сделок"""
    print("Очистка истории сделок...")
    data['deals'] = []
    data['last_clean'] = datetime.datetime.now().isoformat()
    save_sent_deals(data)
    return data


def resolve_redirect(url, max_redirects=5):
    """Рекурсивно разрешает цепочку редиректов до конечного URL"""
    resolved_url = url
    try:
        response = requests.head(
            url,
            allow_redirects=False,
            timeout=10,
            headers={'User-Agent': random.choice(USER_AGENTS)}
        )

        # Если получен редирект (3xx статус)
        if response.is_redirect and 'Location' in response.headers:
            new_url = response.headers['Location']

            # Обработка относительных URL
            if not new_url.startswith('http'):
                parsed = urlparse(url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
                new_url = urllib.parse.urljoin(base_url, new_url)

            # Особенная обработка для Яндекс.Маркета
            if "showcaptcha" in new_url:
                print("Обнаружена капча Яндекса, пропускаем редирект")
                return url  # Возвращаем исходный URL вместо капчи

            # Обработка retpath-параметра в URL Яндекса
            if "market.yandex.ru" in new_url and "retpath=" in new_url:
                try:
                    parsed = urlparse(new_url)
                    query = parse_qs(parsed.query)
                    if 'retpath' in query:
                        retpath = query['retpath'][0]
                        decoded_retpath = urllib.parse.unquote(retpath)

                        # Декодируем только один раз если нужно
                        if decoded_retpath.startswith("aHR0c"):
                            decoded_retpath = base64.b64decode(decoded_retpath).decode('utf-8')

                        return decoded_retpath
                except Exception as e:
                    print(f"Ошибка декодирования retpath: {e}")

            # Рекурсивно обрабатываем следующий редирект
            if max_redirects > 0:
                return resolve_redirect(new_url, max_redirects - 1)
            return new_url

    except Exception as e:
        print(f"Ошибка разрешения редиректа: {e}")

    return resolved_url


def clean_url(url):
    """Очистка URL от трекеров и UTM-меток"""
    if not url:
        return url

    # Удаление параметров отслеживания
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    # Фильтрация нежелательных параметров
    clean_params = {}
    for key, value in query_params.items():
        if not key.startswith(('utm_', '_openstat', 'fbclid', 'gclid', '__rr')):
            clean_params[key] = value

    # Сборка чистого URL
    clean_query = urllib.parse.urlencode(clean_params, doseq=True)
    return urllib.parse.urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        clean_query,
        parsed.fragment
    ))


def parse_deals(html):
    soup = BeautifulSoup(html, 'html.parser')
    deals = []

    items = soup.select('article.card')

    if items:
        print(f"Найдено элементов: {len(items)}")
        for item in items:
            try:
                deal_id = item.get('data-permalink')
                if not deal_id:
                    continue

                title_elem = item.select_one('div.custom-card-title')
                title = title_elem.get_text(strip=True) if title_elem else ''

                desc = ''
                desc_container = item.select_one(
                    '.row-start-3.col-start-1.col-end-5.text-secondary-text-light.items-center.break-long-word')
                if desc_container:
                    desc_elem = desc_container.select_one('span')
                    if desc_elem:
                        desc = desc_elem.get_text(strip=True) if desc_elem else ''

                promocode = ''
                promocode_container = item.select_one('.absolute.w-full.h-full.flex.items-center.justify-between')
                if promocode_container:
                    promocode_elem = promocode_container.select_one(
                        '.order-1.overflow-hidden.overflow-ellipsis.whitespace-nowrap.text-base')
                    if promocode_elem:
                        promocode = promocode_elem.get_text(strip=True) if promocode_elem else ''

                link_elem = item.select_one(
                    'a.w-full.h-full.flex.justify-center.items-center.gtm_buy_now_homepage') or item.select_one(
                    'a.cept-tt')
                final_url = ''
                if link_elem and link_elem.has_attr('href'):
                    raw_url = link_elem['href']
                    if not raw_url.startswith('http'):
                        raw_url = urllib.parse.urljoin('https://www.pepper.ru', raw_url)
                    final_url = clean_url(resolve_redirect(raw_url))

                if 'pepper.ru' in final_url:
                    continue

                # Инициализация ценовых данных пустыми строками
                new_price = ''
                old_price = ''
                discount = ''

                price_container = item.select_one('.flex.items-center.relative.whitespace-nowrap.overflow-hidden')
                if price_container:
                    new_price_elem = price_container.select_one('.text-lg.font-bold.text-primary.mr-2')
                    old_price_elem = price_container.select_one('.text-lg.line-through.text-secondary-text-light')
                    discount_elem = price_container.select_one('.text-sm.text-secondary-text-light')

                    if new_price_elem:
                        new_price = new_price_elem.get_text(strip=True)
                    if old_price_elem:
                        old_price = old_price_elem.get_text(strip=True)
                    if discount_elem:
                        discount = discount_elem.get_text(strip=True)

                deals.append({
                    'id': deal_id,
                    'title': title,
                    'description': desc,
                    'promocode': promocode,
                    'new_price': new_price,
                    'old_price': old_price,
                    'discount': discount,
                    'link': final_url
                })
            except Exception as e:
                print(f"Ошибка парсинга: {e}")
                continue

    else:
        print("Сделки не найдены")

    return deals


def send_to_telegram(deal):
    try:
        # Экранирование текстовых данных
        title = html.escape(deal['title'])
        description = html.escape(deal['description'])
        promocode = html.escape(deal['promocode'])
        old_price = html.escape(deal['old_price'])
        new_price = html.escape(deal['new_price'])

        # Удаление скобок из скидки
        discount = html.escape(deal['discount']).replace('(', '').replace(')', '')
        link = deal['link']

        # Формирование сообщения только с доступными данными
        message_lines = [f"🔥 <b>{title}</b>"]

        if description:
            description = description.replace('Показать ещё', '')
            message_lines.append(f"{description}")

        if old_price:
            message_lines.append(f"💰 Старая цена: <s>{old_price}</s>")

        if new_price:
            message_lines.append(f"✅ Новая цена: <b>{new_price}</b>")

        if discount:
            message_lines.append(f"📉 Скидка: <b>{discount}</b>")

        if promocode:
            message_lines.append(f"Промокод: <b>{promocode}</b>")

        if link:
            message_lines.append(f"🔗 <a href='{link}'>Ссылка на товар</a>")

        message = "\n\n".join(message_lines)

        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': TELEGRAM_CHANNEL_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': False
        }

        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Ошибка отправки в Telegram: {response.text}")
    except Exception as e:
        print(f"Ошибка при отправке в Telegram: {e}")


def main():
    """Основная функция выполнения скрипта"""
    print("Запуск парсера Pepper.ru в фоновом режиме...")
    print(f"Парсинг каждые 2 минуты, очистка истории каждые {CLEAN_INTERVAL_DAYS} дней")

    # Загрузка начальных данных
    sent_data = load_sent_deals()

    # Основной цикл работы
    while True:
        try:
            # Проверка необходимости очистки истории
            if should_clean_history(sent_data):
                sent_data = clean_history(sent_data)
                print(f"История очищена. Следующая очистка через {CLEAN_INTERVAL_DAYS} дней.")

            print("\n" + "=" * 50)
            print(f"Начало нового цикла парсинга: {time.strftime('%Y-%m-%d %H:%M:%S')}")

            driver = None
            try:
                driver = setup_driver()

                # Загрузка страницы с рандомными задержками
                print("Загрузка страницы...")
                driver.get(PEPPER_URL)
                time.sleep(random.uniform(5, 10))

                # Прокрутка для загрузки контента
                print("Прокрутка страницы для загрузки контента...")
                scroll_pause_time = 2
                screen_height = driver.execute_script("return window.screen.height;")
                scrolls = 5

                for i in range(scrolls):
                    driver.execute_script(f"window.scrollTo(0, {screen_height * (i + 1) / scrolls});")
                    time.sleep(scroll_pause_time)
                    print(f"Прокрутка {i + 1}/{scrolls} завершена")

                # Ожидание появления контента
                print("Ожидание загрузки контента...")
                try:
                    WebDriverWait(driver, 30).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "article"))
                    )
                    print("Контент загружен")
                except Exception as e:
                    print(f"Ошибка ожидания контента: {e}")

                # Получение HTML и парсинг
                page_source = driver.page_source
                deals = parse_deals(page_source)

                print(f"Найдено {len(deals)} скидок")

                # Отправка новых сделок
                new_count = 0
                for deal in deals:
                    if deal['id'] not in sent_data['deals']:
                        print(f"Отправка новой сделки: {deal['title']}")
                        send_to_telegram(deal)
                        sent_data['deals'].append(deal['id'])
                        new_count += 1
                        time.sleep(random.uniform(3, 6))  # Случайная задержка

                # Сохранение обновленных данных
                save_sent_deals(sent_data)
                print(f"Отправлено новых сделок: {new_count}")

            except Exception as e:
                print(f"Ошибка во время парсинга: {e}")
            finally:
                if driver:
                    driver.quit()

            print(f"Цикл завершен. Ожидание следующего запуска...")
            print("=" * 50 + "\n")

        except Exception as e:
            print(f"Критическая ошибка в основном цикле: {e}")

        # Пауза перед следующим запуском (10 минут)
        time.sleep(10 * 60)


if __name__ == "__main__":
    main()

