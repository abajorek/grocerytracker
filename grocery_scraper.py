#!/usr/bin/env python3
"""
Multi-Store Grocery Price Comparison Tool
Scrapes prices from Walmart, Safeway, Sprouts, Sam's Club, and City Market
"""

import asyncio
import json
import time
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
import logging

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from fuzzywuzzy import fuzz
import pandas as pd


@dataclass
class Product:
    """Represents a product with normalized attributes"""
    name: str
    brand: str = ""
    size: str = ""
    unit: str = ""
    category: str = ""
    keywords: List[str] = None
    
    def __post_init__(self):
        if self.keywords is None:
            self.keywords = []


@dataclass
class PriceRecord:
    """Represents a price record from a store"""
    store: str
    product_name: str
    brand: str
    price: float
    size: str
    unit: str
    url: str
    timestamp: datetime
    availability: bool = True
    original_text: str = ""


class StoreScraperBase:
    """Base class for store scrapers"""
    
    def __init__(self, store_name: str, base_url: str):
        self.store_name = store_name
        self.base_url = base_url
        self.session = requests.Session()
        self.driver = None
        self.logger = logging.getLogger(f"{store_name}_scraper")
        
    def setup_driver(self):
        """Setup Selenium WebDriver with stealth options"""
        chrome_options = Options()
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        # chrome_options.add_argument("--headless")  # Uncomment for headless mode
        
        self.driver = webdriver.Chrome(options=chrome_options)
        return self.driver
    
    def login(self, username: str, password: str) -> bool:
        """Login to store website - to be overridden by each store"""
        raise NotImplementedError
    
    def search_product(self, product: Product) -> List[PriceRecord]:
        """Search for product - to be overridden by each store"""
        raise NotImplementedError
    
    def cleanup(self):
        """Clean up resources"""
        if self.driver:
            self.driver.quit()


class WalmartScraper(StoreScraperBase):
    """Walmart.com scraper"""
    
    def __init__(self):
        super().__init__("Walmart", "https://www.walmart.com")
    
    def login(self, username: str, password: str) -> bool:
        """Login to Walmart"""
        try:
            self.setup_driver()
            self.driver.get("https://www.walmart.com/account/login")
            
            # Wait for login form
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "email"))
            )
            password_field = self.driver.find_element(By.ID, "password")
            
            email_field.send_keys(username)
            password_field.send_keys(password)
            
            # Submit
            submit_btn = self.driver.find_element(By.CSS_SELECTOR, "[data-automation-id='signin-submit-btn']")
            submit_btn.click()
            
            # Wait for redirect
            WebDriverWait(self.driver, 10).until(
                lambda d: "account/login" not in d.current_url
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Walmart login failed: {e}")
            return False
    
    def search_product(self, product: Product) -> List[PriceRecord]:
        """Search Walmart for product"""
        results = []
        
        try:
            search_terms = [
                f"{product.brand} {product.name}".strip(),
                product.name,
                *product.keywords
            ]
            
            for search_term in search_terms:
                if not search_term:
                    continue
                    
                search_url = f"{self.base_url}/search?q={search_term.replace(' ', '+')}"
                self.driver.get(search_url)
                
                time.sleep(2)  # Let page load
                
                # Find product tiles
                products = self.driver.find_elements(By.CSS_SELECTOR, "[data-testid='item-stack']")
                
                for prod in products[:5]:  # Limit to top 5 results
                    try:
                        # Extract product info
                        name_elem = prod.find_element(By.CSS_SELECTOR, "[data-automation-id='product-title']")
                        price_elem = prod.find_element(By.CSS_SELECTOR, "[itemprop='price']")
                        
                        product_name = name_elem.text
                        price_text = price_elem.get_attribute('content')
                        price = float(price_text) if price_text else 0.0
                        
                        # Get product URL
                        link_elem = prod.find_element(By.CSS_SELECTOR, "a")
                        product_url = link_elem.get_attribute('href')
                        
                        # Extract size/brand info from title
                        brand, size, unit = self._parse_walmart_title(product_name)
                        
                        record = PriceRecord(
                            store="Walmart",
                            product_name=product_name,
                            brand=brand,
                            price=price,
                            size=size,
                            unit=unit,
                            url=product_url,
                            timestamp=datetime.now(),
                            original_text=product_name
                        )
                        
                        results.append(record)
                        
                    except Exception as e:
                        self.logger.warning(f"Error parsing Walmart product: {e}")
                        continue
                
                # Don't search with all terms if we found good results
                if len(results) >= 3:
                    break
                    
                time.sleep(1)  # Be polite
                
        except Exception as e:
            self.logger.error(f"Walmart search failed: {e}")
            
        return results
    
    def _parse_walmart_title(self, title: str) -> Tuple[str, str, str]:
        """Parse Walmart product title to extract brand, size, unit"""
        # Common patterns for Walmart titles
        size_patterns = [
            r'(\d+\.?\d*)\s*(oz|lb|lbs|g|kg|ml|l|ct|count|pack)',
            r'(\d+\.?\d*)-?(oz|lb|lbs|g|kg|ml|l|ct|count|pack)',
        ]
        
        brand = ""
        size = ""
        unit = ""
        
        # Extract size and unit
        for pattern in size_patterns:
            match = re.search(pattern, title.lower())
            if match:
                size = match.group(1)
                unit = match.group(2)
                break
        
        # Extract brand (usually first word or two)
        words = title.split()
        if len(words) > 0:
            brand = words[0]
            
        return brand, size, unit


class SafewayScraper(StoreScraperBase):
    """Safeway.com scraper"""
    
    def __init__(self):
        super().__init__("Safeway", "https://www.safeway.com")
    
    def login(self, username: str, password: str) -> bool:
        """Login to Safeway"""
        try:
            self.setup_driver()
            self.driver.get("https://www.safeway.com/account/sign-in.html")
            
            # Handle email input
            email_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "label-email"))
            )
            email_field.send_keys(username)
            
            # Continue to password
            continue_btn = self.driver.find_element(By.ID, "btnSignIn")
            continue_btn.click()
            
            # Password input
            password_field = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, "label-password"))
            )
            password_field.send_keys(password)
            
            # Final submit
            submit_btn = self.driver.find_element(By.ID, "btnSignIn")
            submit_btn.click()
            
            # Wait for redirect
            time.sleep(3)
            
            return "sign-in" not in self.driver.current_url
            
        except Exception as e:
            self.logger.error(f"Safeway login failed: {e}")
            return False
    
    def search_product(self, product: Product) -> List[PriceRecord]:
        """Search Safeway for product"""
        results = []
        
        try:
            search_term = f"{product.brand} {product.name}".strip() or product.name
            
            # Navigate to search
            search_url = f"{self.base_url}/shop/search-results.html?q={search_term.replace(' ', '+')}"
            self.driver.get(search_url)
            
            time.sleep(3)  # Let page load
            
            # Find product cards
            products = self.driver.find_elements(By.CSS_SELECTOR, ".product-item-inner")
            
            for prod in products[:5]:
                try:
                    # Product name
                    name_elem = prod.find_element(By.CSS_SELECTOR, ".product-title a")
                    product_name = name_elem.text
                    product_url = name_elem.get_attribute('href')
                    
                    # Price
                    price_elem = prod.find_element(By.CSS_SELECTOR, ".product-price .notranslate")
                    price_text = re.search(r'[\d.]+', price_elem.text)
                    price = float(price_text.group()) if price_text else 0.0
                    
                    # Parse brand/size from title
                    brand, size, unit = self._parse_safeway_title(product_name)
                    
                    record = PriceRecord(
                        store="Safeway",
                        product_name=product_name,
                        brand=brand,
                        price=price,
                        size=size,
                        unit=unit,
                        url=product_url,
                        timestamp=datetime.now(),
                        original_text=product_name
                    )
                    
                    results.append(record)
                    
                except Exception as e:
                    self.logger.warning(f"Error parsing Safeway product: {e}")
                    continue
                    
            time.sleep(1)
            
        except Exception as e:
            self.logger.error(f"Safeway search failed: {e}")
            
        return results
    
    def _parse_safeway_title(self, title: str) -> Tuple[str, str, str]:
        """Parse Safeway product title"""
        # Similar parsing logic as Walmart but adapted for Safeway format
        size_patterns = [
            r'(\d+\.?\d*)\s*(oz|lb|lbs|g|kg|ml|l|ct|count|pack)',
        ]
        
        brand = ""
        size = ""
        unit = ""
        
        for pattern in size_patterns:
            match = re.search(pattern, title.lower())
            if match:
                size = match.group(1)
                unit = match.group(2)
                break
        
        words = title.split()
        if len(words) > 0:
            brand = words[0]
            
        return brand, size, unit


class PriceComparator:
    """Main class to coordinate price comparison"""
    
    def __init__(self):
        self.scrapers = {
            'walmart': WalmartScraper(),
            'safeway': SafewayScraper(),
            # Add other scrapers here
        }
        self.price_history = []
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger("PriceComparator")
    
    def add_credentials(self, store: str, username: str, password: str):
        """Add login credentials for a store"""
        if store in self.scrapers:
            # Store credentials securely (in real app, use proper encryption)
            self.scrapers[store].username = username
            self.scrapers[store].password = password
    
    def compare_prices(self, product: Product) -> Dict:
        """Compare prices across all stores"""
        all_results = []
        
        for store_name, scraper in self.scrapers.items():
            try:
                # Login if needed
                if hasattr(scraper, 'username') and hasattr(scraper, 'password'):
                    self.logger.info(f"Logging into {store_name}...")
                    if not scraper.login(scraper.username, scraper.password):
                        self.logger.warning(f"Failed to login to {store_name}")
                        continue
                
                # Search for product
                self.logger.info(f"Searching {store_name} for: {product.name}")
                results = scraper.search_product(product)
                all_results.extend(results)
                
                # Add delay between stores
                time.sleep(2)
                
            except Exception as e:
                self.logger.error(f"Error with {store_name}: {e}")
                continue
        
        # Clean up
        for scraper in self.scrapers.values():
            scraper.cleanup()
        
        # Process and rank results
        ranked_results = self._rank_results(product, all_results)
        
        # Store in history
        self.price_history.extend(all_results)
        
        return {
            'product': asdict(product),
            'results': [asdict(result) for result in ranked_results],
            'best_deal': asdict(ranked_results[0]) if ranked_results else None,
            'timestamp': datetime.now().isoformat()
        }
    
    def _rank_results(self, target_product: Product, results: List[PriceRecord]) -> List[PriceRecord]:
        """Rank results by relevance and price"""
        scored_results = []
        
        for result in results:
            # Calculate relevance score
            name_similarity = fuzz.partial_ratio(
                target_product.name.lower(), 
                result.product_name.lower()
            )
            
            brand_similarity = fuzz.ratio(
                target_product.brand.lower(),
                result.brand.lower()
            ) if target_product.brand and result.brand else 50
            
            # Combined score (70% name, 30% brand)
            relevance_score = (name_similarity * 0.7) + (brand_similarity * 0.3)
            
            scored_results.append((result, relevance_score))
        
        # Sort by relevance first, then by price
        scored_results.sort(key=lambda x: (-x[1], x[0].price))
        
        return [result for result, score in scored_results if score > 60]  # Filter low relevance
    
    def save_results(self, filename: str = None):
        """Save price history to file"""
        if filename is None:
            filename = f"price_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump([asdict(record) for record in self.price_history], f, default=str, indent=2)
        
        self.logger.info(f"Results saved to {filename}")
    
    def load_shopping_list(self, filename: str) -> List[Product]:
        """Load shopping list from JSON file"""
        with open(filename, 'r') as f:
            data = json.load(f)
        
        return [Product(**item) for item in data]


# Example usage and shopping list setup
def main():
    """Main function to demonstrate usage"""
    
    # Create comparator
    comparator = PriceComparator()
    
    # Add store credentials (replace with your actual credentials)
    comparator.add_credentials('walmart', 'your_walmart_email@email.com', 'your_password')
    comparator.add_credentials('safeway', 'your_safeway_email@email.com', 'your_password')
    
    # Define some common products
    shopping_list = [
        Product(
            name="Bananas",
            brand="",
            category="produce",
            keywords=["banana", "bananas"]
        ),
        Product(
            name="Milk",
            brand="",
            size="1",
            unit="gallon",
            category="dairy",
            keywords=["whole milk", "2% milk"]
        ),
        Product(
            name="Bread",
            brand="Wonder",
            category="bakery",
            keywords=["white bread", "sandwich bread"]
        ),
        Product(
            name="Chicken Breast",
            brand="",
            category="meat",
            keywords=["boneless chicken breast", "chicken breast boneless"]
        ),
        Product(
            name="Rice",
            brand="",
            size="20",
            unit="lb",
            category="pantry",
            keywords=["white rice", "jasmine rice"]
        )
    ]
    
    # Compare prices for each product
    for product in shopping_list:
        print(f"\n{'='*50}")
        print(f"Comparing prices for: {product.name}")
        print('='*50)
        
        comparison = comparator.compare_prices(product)
        
        if comparison['results']:
            print(f"Found {len(comparison['results'])} results:")
            for i, result in enumerate(comparison['results'][:3], 1):
                print(f"{i}. {result['store']}: ${result['price']:.2f} - {result['product_name']}")
            
            if comparison['best_deal']:
                best = comparison['best_deal']
                print(f"\n🏆 Best Deal: {best['store']} - ${best['price']:.2f}")
        else:
            print("No results found")
        
        # Small delay between products
        time.sleep(5)
    
    # Save all results
    comparator.save_results()


if __name__ == "__main__":
    main()