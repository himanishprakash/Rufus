import nest_asyncio
nest_asyncio.apply()

import asyncio
import json
import re
from urllib.parse import urljoin
import time
import os
from datetime import datetime
import logging
from typing import Dict, List, Set, Any
from openai import OpenAI
from playwright.async_api import async_playwright

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('semantic_crawler.log'),
        logging.StreamHandler()
    ]
)

class Rufus:
    def __init__(self, api_key: str):
        """
        Initialize the semantic web crawler.
        
        Args:
            api_key (str): OpenAI API key for semantic analysis
        """
        
        
        self.client = OpenAI(api_key=api_key)
        self.visited_urls: Set[str] = set()
        self.page_relevance: Dict[str, bool] = {}
        self.page_data: Dict[str, Dict[str, Any]] = {}
        self.depth_data: Dict[int, List[str]] = {}
        self.keywords: List[str] = []

    async def get_semantic_keywords(self, instruction: str) -> List[str]:
        """
        Generate semantically related keywords for the search instruction.
        """
        
        
        prompt = f"""Generate semantically related keywords and phrases for this instruction:
        
        Instruction: "{instruction}"
        
        Consider:
        1. Direct synonyms and related terms
        2. Industry-specific terminology
        3. Common abbreviations
        4. Related concepts and topics
        5. Contextual variations
        
        Return ONLY a comma-separated list of keywords, no explanations."""

        try:
            response = self.client.chat.completions.create(
                model="o1-mini",
                messages=[
                    {"role": "system", "content": "You are a semantic analysis expert. Return only a comma-separated list of keywords."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            keywords = [kw.strip() for kw in response.choices[0].message.content.split(',')]
            logging.info(f"Generated keywords: {keywords}")
            return keywords
            
        except Exception as e:
            logging.error(f"Error generating keywords: {str(e)}")
            return []

    def is_content_relevant(self, content: str, instruction: str, keywords: List[str]) -> bool:
        """
        Determine if page content is relevant using semantic analysis.
        """
        
        
        prompt = f"""Analyze if this content is relevant to the instruction and keywords.

        Instruction: "{instruction}"
        Keywords: {', '.join(keywords)}
        
        Content (excerpt):
        \"\"\"
        {content[:2000]}
        \"\"\"
        
        Consider:
        1. Direct keyword matches
        2. Semantic relationship to instruction
        3. Context and meaning
        4. Content quality and depth
        5. Information value
        
        Answer ONLY with TRUE or FALSE."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a content relevance analyst. Respond only with TRUE or FALSE."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            is_relevant = response.choices[0].message.content.strip().upper() == "TRUE"
            logging.info(f"Content relevance: {is_relevant}")
            return is_relevant
            
        except Exception as e:
            logging.error(f"Error checking content relevance: {str(e)}")
            return False

    async def should_follow_link(self, link_text: str, href: str, 
                               instruction: str, keywords: List[str], 
                               surrounding_text: str = "") -> bool:
        """
        Determine if a link should be followed based on semantic analysis.
        """
        
        
        
        prompt = f"""Should we follow this link based on the instruction and context?
        
        Instruction: "{instruction}"
        Keywords: {', '.join(keywords)}
        
        Link Analysis:
        - Link Text: "{link_text}"
        - URL: {href}
        - Surrounding Context: "{surrounding_text}"
        
        Consider:
        1. Relevance to instruction
        2. Keyword matches
        3. URL structure/path
        4. Link context
        5. Potential information value
        
        Answer ONLY with TRUE or FALSE."""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a link relevance analyst. Respond only with TRUE or FALSE."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            should_follow = response.choices[0].message.content.strip().upper() == "TRUE"
            logging.info(f"Should follow {href}: {should_follow}")
            return should_follow
            
        except Exception as e:
            logging.error(f"Error checking link relevance: {str(e)}")
            return False

    async def analyze_page_links(self, page, current_url: str, base_url: str, 
                               instruction: str) -> Dict[str, bool]:
        """
        Analyze all links on the current page for relevance.
        """
        
        
        link_relevance = {}
        try:
            links = await page.query_selector_all('a[href]')
            for link in links:
                href = await link.get_attribute('href')
                if href:
                    absolute_url = urljoin(current_url, href)
                    if absolute_url.startswith(base_url) and absolute_url not in self.visited_urls:
                        link_text = await link.inner_text()
                        parent = await link.evaluate('element => element.parentElement.textContent')
                        surrounding_text = parent[:200] if parent else ""
                        
                        is_relevant = await self.should_follow_link(
                            link_text, absolute_url, instruction, 
                            self.keywords, surrounding_text
                        )
                        link_relevance[absolute_url] = is_relevant
            
            return link_relevance
            
        except Exception as e:
            logging.error(f"Error in link analysis: {str(e)}")
            return link_relevance

    async def crawl_page(self, page, current_url: str, base_url: str, instruction: str, 
                        depth: int = 0, max_depth: int = 2):
        """
        Crawl a page and analyze its content and links.
        """
        
        
        if depth > max_depth or current_url in self.visited_urls:
            return
            
        self.visited_urls.add(current_url)
        
        if depth not in self.depth_data:
            self.depth_data[depth] = []
        
        try:
            # Generate keywords if not already done
            if not self.keywords:
                self.keywords = await self.get_semantic_keywords(instruction)
            
            await page.goto(current_url)
            logging.info(f"Crawling depth {depth}: {current_url}")
            
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(1)
            
            # Get and analyze content
            content = await page.inner_text('body')
            is_relevant = self.is_content_relevant(content, instruction, self.keywords)
            self.page_relevance[current_url] = is_relevant
            
            # Store relevant page data
            if is_relevant:
                self.page_data[current_url] = {
                    'url': current_url,
                    'depth': depth,
                    'content': content,
                    'crawl_time': datetime.now().isoformat(),
                    'title': await page.title(),
                    'matched_keywords': self.keywords
                }
                self.depth_data[depth].append(current_url)
            
            # Analyze and follow links if not at max depth
            if depth < max_depth:
                link_relevance = await self.analyze_page_links(page, current_url, base_url, instruction)
                
                for url, relevant in link_relevance.items():
                    if relevant and url not in self.visited_urls:
                        await self.crawl_page(
                            page, url, base_url, instruction, 
                            depth + 1, max_depth
                        )
                        
        except Exception as e:
            logging.error(f"Error crawling {current_url}: {str(e)}")

    def save_results(self, base_url: str, instruction: str):
        """
        Save crawl results to JSON file.
        """
        
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'semantic_results_{timestamp}.json'
        
        results = {
            'metadata': {
                'base_url': base_url,
                'instruction': instruction,
                'crawl_time': datetime.now().isoformat(),
                'total_pages': len(self.visited_urls),
                'relevant_pages': sum(1 for v in self.page_relevance.values() if v),
                'keywords_used': self.keywords
            },
            'relevance_map': self.page_relevance,
            'depth_analysis': {
                str(depth): {
                    'urls': urls,
                    'count': len(urls)
                } for depth, urls in self.depth_data.items()
            },
            'page_data': self.page_data
        }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        logging.info(f"Results saved to {filename}")
        return filename

    async def crawl(self, base_url: str, instruction: str, max_depth: int = 2):
        """
        Main crawling function.
        """
        
        
        if not base_url.startswith(('http://', 'https://')):
            base_url = 'https://' + base_url
        if not base_url.endswith('/'):
            base_url += '/'
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await self.crawl_page(page, base_url, base_url, instruction, max_depth=max_depth)
                filename = self.save_results(base_url, instruction)
                logging.info(f"Crawl completed successfully. Results saved to {filename}")
                
            except Exception as e:
                logging.error(f"Crawl failed: {str(e)}")
            finally:
                await browser.close()

async def main():
    """
    Main function to run the crawler.
    """
    print("Semantic Web Crawler")
    print("-" * 50)
    
    api_key = os.getenv('OPENAI_API_KEY')
    base_url = input("Enter the base URL to crawl: ").strip()
    instruction = input("Enter your search instruction: ").strip()
    max_depth = int(input("Enter maximum crawl depth (default 2): ") or "2")
    
    print("\nStarting crawl...")
    crawler = Rufus(api_key)
    await crawler.crawl(base_url, instruction, max_depth)
    print("Crawl completed!")

if __name__ == "__main__":
    asyncio.run(main())