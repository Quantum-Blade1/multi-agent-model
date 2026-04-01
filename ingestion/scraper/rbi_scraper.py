"""
Module for scraping RBI notifications and circulars.
"""
import time
import json
import os
from typing import List, Dict
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ingestion.config import settings

class RBIScraper:
    """
    Scraper class for RBI circulars and notifications.
    """
    def __init__(self):
        self.session = self._create_session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.34 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.34",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _create_session(self) -> requests.Session:
        """
        Creates a requests session with retry logic.
        """
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 503],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def scrape_circular_links(self, category: str) -> List[Dict]:
        """
        Hits RBI_CIRCULAR_BASE_URL with category filter param and parses the HTML table.
        """
        print(f"Scraping circulars for category: {category}")
        params = {"Category": category}
        try:
            response = self.session.get(
                settings.RBI_CIRCULAR_BASE_URL,
                params=params,
                headers=self.headers,
                timeout=15
            )
            response.raise_for_status()
            time.sleep(1)  # Rate limiting
            
            soup = BeautifulSoup(response.text, "lxml")
            circulars = []
            
            # The RBI website structure typically uses tables for list display.
            # We look for the main table where circulars are listed.
            # Note: This is an estimation of the table structure.
            table = soup.find("table", {"class": "table-border"}) or soup.find("table")
            if not table:
                print(f"No table found for category: {category}")
                return []

            rows = table.find_all("tr")[1:]  # Skip header row
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 2:
                    link_tag = cols[1].find("a")
                    if link_tag:
                        title = link_tag.get_text(strip=True)
                        url = link_tag.get("href")
                        if url and not url.startswith("http"):
                            url = "https://www.rbi.org.in/Scripts/" + url
                        
                        date = cols[0].get_text(strip=True)
                        circulars.append({
                            "title": title,
                            "url": url,
                            "date": date,
                            "category": category
                        })
            
            return circulars
        except Exception as e:
            print(f"Error scraping category {category}: {e}")
            return []

    def scrape_master_circular(self, url: str) -> Dict:
        """
        Fetches the master circular page and returns metadata.
        """
        try:
            response = self.session.get(url, headers=self.headers, timeout=15)
            response.raise_for_status()
            time.sleep(1)  # Rate limiting
            
            soup = BeautifulSoup(response.text, "lxml")
            title = soup.find("title").get_text(strip=True) if soup.find("title") else "Master Circular"
            
            return {
                "title": title,
                "url": url,
                "date": "N/A",  # Would require specific parsing from the page content
                "type": "master"
            }
        except Exception as e:
            print(f"Error scraping master circular at {url}: {e}")
            return {}

    def scrape_all(self, categories: List[str]) -> List[Dict]:
        """
        Calls scrape_circular_links for each category, deduplicates by URL, and saves to file.
        """
        all_circulars = []
        seen_urls = set()
        
        for category in categories:
            circulars = self.scrape_circular_links(category)
            for circ in circulars:
                if circ["url"] not in seen_urls:
                    all_circulars.append(circ)
                    seen_urls.add(circ["url"])
        
        # Save raw link list to RAW_DATA_DIR/circular_links.json
        os.makedirs(settings.RAW_DATA_DIR, exist_ok=True)
        save_path = os.path.join(settings.RAW_DATA_DIR, "circular_links.json")
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(all_circulars, f, indent=4)
            
        print(f"Saved {len(all_circulars)} circular links to {save_path}")
        return all_circulars

def scrape_rbi():
    """
    Utility function to trigger scraping based on config.
    """
    scraper = RBIScraper()
    return scraper.scrape_all(settings.TARGET_CATEGORIES)
