import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
import requests
from supabase import create_client

STOCKED_FISH_ENDPOINT = 'https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/StockedFish_View/FeatureServer/0/query'
STOCKING_BODIES_ENDPOINT = 'https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/Stocking_Waterbodies_(Joined_View)/FeatureServer/1/query'

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_SERVICE_KEY = os.environ['SUPABASE_SERVICE_KEY']

GMAIL_USER = os.environ['GMAIL_USER']
GMAIL_APP_PASSWORD = os.environ['GMAIL_APP_PASSWORD']

WEB_APP_URL = os.environ.get('WEB_APP_URL', 'https://YOUR_GITHUB_USERNAME.github.io/fish-stocking')

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


SPECIES_MAP = {
    'RT': 'Rainbow Trout',
    'BT': 'Brown Trout',
    'EBT': 'Eastern Brook Trout',
    'S': 'Broodstock Salmon',
    'TT': 'Tiger Trout',
}


def get_stocked_fish():
    params = {
        'f': 'json',
        'resultOffset': 0,
        'returnGeometry': 'false',
        'where': '1=1',
        'outFields': '*',
        'orderByFields': 'Stocked_Date DESC',
    }
    response = requests.get(STOCKED_FISH_ENDPOINT, params=params)
    response.raise_for_status()
    return response.json()['features']


def get_coming_soon():
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    params = {
        'f': 'json',
        'resultOffset': 0,
        'returnGeometry': 'false',
        'where': (
            f" ( ( (Planned = 'Y') AND (join_count IS NULL) ) OR "
            f"( ( (Planned = 'Y') AND (join_count IS NOT NULL) ) "
            f"AND (Stocked_Date_min > timestamp '{now}') ) ) "
        ),
        'outFields': 'Waterbody,Town_1,Stocked_Date_min',
    }
    response = requests.get(STOCKING_BODIES_ENDPOINT, params=params)
    response.raise_for_status()
    return response.json()['features']


def get_last_seen_ids():
    result = supabase.table('stocking_state').select('last_seen_ids').eq('id', 1).single().execute()
    return set(result.data['last_seen_ids'])


def save_seen_ids(ids):
    supabase.table('stocking_state').update({
        'last_seen_ids': list(ids),
        'updated_at': datetime.utcnow().isoformat(),
    }).eq('id', 1).execute()


def find_new_stockings(last_seen_ids, all_stockings):
    return [s for s in all_stockings if s['attributes']['OBJECTID'] not in last_seen_ids]


def prettify_stocking(item):
    attrs = item['attributes']
    return {
        'town': attrs['Town'],
        'waterbody': attrs['Waterbody'].split(' - ')[0],
        'species': SPECIES_MAP.get(attrs['Species'], attrs['Species']),
        'loaded_number': attrs.get('Loaded_Number') or '',
        'stocked_date': datetime.fromtimestamp(attrs['Stocked_Date'] / 1000).strftime('%Y-%m-%d'),
    }


def get_all_subscribers():
    """Returns a dict of {email: set_of_towns}."""
    result = supabase.table('subscriptions').select('users(email), filter_value').execute()
    subscribers = {}
    for row in result.data:
        email = row['users']['email']
        if email not in subscribers:
            subscribers[email] = set()
        subscribers[email].add(row['filter_value'].lower())
    return subscribers


def stockings_for_subscriber(new_stockings, subscribed_towns):
    return [s for s in new_stockings if s['town'].lower() in subscribed_towns]


def format_email_html(stockings, coming_soon, recipient_email):
    manage_url = f"{WEB_APP_URL}/manage.html?email={requests.utils.quote(recipient_email)}"

    html = """
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; color: #222;">
    """

    html += "<h2 style='color:#2a6496'>New Stockings</h2>"
    html += """
    <table style='border-collapse:collapse; width:100%'>
      <thead>
        <tr style='background:#2a6496; color:white'>
          <th style='padding:8px; text-align:left'>Town</th>
          <th style='padding:8px; text-align:left'>Waterbody</th>
          <th style='padding:8px; text-align:left'>Species</th>
          <th style='padding:8px; text-align:left'># Stocked</th>
          <th style='padding:8px; text-align:left'>Date</th>
        </tr>
      </thead>
      <tbody>
    """
    for i, s in enumerate(stockings):
        bg = '#f5f5f5' if i % 2 == 0 else '#ffffff'
        html += f"""
        <tr style='background:{bg}'>
          <td style='padding:8px'>{s['town']}</td>
          <td style='padding:8px'>{s['waterbody']}</td>
          <td style='padding:8px'>{s['species']}</td>
          <td style='padding:8px'>{s['loaded_number']}</td>
          <td style='padding:8px'>{s['stocked_date']}</td>
        </tr>
        """
    html += "</tbody></table><br>"

    if coming_soon:
        html += "<h2 style='color:#2a6496'>Coming Soon</h2>"
        html += """
        <table style='border-collapse:collapse; width:100%'>
          <thead>
            <tr style='background:#2a6496; color:white'>
              <th style='padding:8px; text-align:left'>Town</th>
              <th style='padding:8px; text-align:left'>Waterbody</th>
              <th style='padding:8px; text-align:left'>Planned Date</th>
            </tr>
          </thead>
          <tbody>
        """
        for i, item in enumerate(coming_soon):
            bg = '#f5f5f5' if i % 2 == 0 else '#ffffff'
            town = item['attributes']['Town_1']
            waterbody = item['attributes']['Waterbody']
            raw_date = item['attributes'].get('Stocked_Date_min')
            planned_date = datetime.fromtimestamp(raw_date / 1000).strftime('%Y-%m-%d') if raw_date else 'TBD'
            html += f"""
            <tr style='background:{bg}'>
              <td style='padding:8px'>{town}</td>
              <td style='padding:8px'>{waterbody}</td>
              <td style='padding:8px'>{planned_date}</td>
            </tr>
            """
        html += "</tbody></table><br>"

    html += f"""
    <hr style='border:none; border-top:1px solid #ddd; margin:24px 0'>
    <p style='font-size:12px; color:#888'>
      <a href='{manage_url}'>Manage your subscriptions</a> &nbsp;|&nbsp;
      <a href='{manage_url}&action=unsubscribe'>Unsubscribe</a>
    </p>
    </div>
    """
    return html


def send_email(to_email, subject, html_body):
    message = MIMEMultipart('alternative')
    message['From'] = GMAIL_USER
    message['To'] = to_email
    message['Subject'] = subject
    message.attach(MIMEText(html_body, 'html'))

    with smtplib.SMTP('smtp.gmail.com', 587) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, to_email, message.as_string())


def main():
    print('Fetching stocking data...')
    all_stockings = get_stocked_fish()
    coming_soon = get_coming_soon()

    last_seen_ids = get_last_seen_ids()
    new_raw = find_new_stockings(last_seen_ids, all_stockings)

    current_ids = {s['attributes']['OBJECTID'] for s in all_stockings}
    save_seen_ids(current_ids)

    if not new_raw:
        print('No new stockings.')
        return

    new_stockings = [prettify_stocking(s) for s in new_raw]
    print(f'Found {len(new_stockings)} new stocking(s).')

    subscribers = get_all_subscribers()
    print(f'Checking against {len(subscribers)} subscriber(s)...')

    for email, towns in subscribers.items():
        relevant = stockings_for_subscriber(new_stockings, towns)
        if relevant:
            relevant_coming_soon = [
                item for item in coming_soon
                if item['attributes']['Town_1'] and item['attributes']['Town_1'].lower() in towns
            ]
            html = format_email_html(relevant, relevant_coming_soon, email)
            send_email(email, 'Fish Stocking Alert', html)
            print(f'Emailed {email} about {len(relevant)} stocking(s).')


if __name__ == '__main__':
    main()
