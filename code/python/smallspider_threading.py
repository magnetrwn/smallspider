# Imports
#
from threading import Lock
import logging
import sys
import threading
import requests


# Class: SmallSpider
# Description: setup a webpage spider
# TODO: due to the Python GIL, threading does not work well here. Try multiprocessing.
#
class SmallSpider:
  DEFAULT_MAX_QUEUE_PAGES = 4000    # Max pages to queue up to search
  DEFAULT_MAX_VISITED_PAGES = 200   # Total pages to visit
  DEFAULT_MAX_PARSABLE_URLS = None  # Max links found in a page that can be added to the queue
  DEFAULT_MAX_THREADS = 4

  DEFAULT_AVOID_STRINGS = ['?', '&', '!', '{', '}', '%', ' ', '\n', ',', ':',
                           ';', '|', '#', '\"', '\'', 'cloudflare']

  DEFAULT_SEARCH_STRINGS = ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico']

  DEFAULT_LINK_DELIMITERS = [('src=\'' , '\'' ),  # HTML
                             ('src=\"' , '\"' ),
                             ('href=\'', '\'' ),
                             ('href=\"', '\"' ),
                             ('url(\'' , '\')'),  # CSS
                             ('url(\"' , '\")'),
                             ('url('   , ')'  )]

  # Method: __init__
  # Description: creates a SmallSpider object and applies custom settings if present.
  #
  def __init__(self,
               max_queue_pages=DEFAULT_MAX_QUEUE_PAGES,
               max_visited_pages=DEFAULT_MAX_VISITED_PAGES,
               max_parsable_urls=DEFAULT_MAX_PARSABLE_URLS,
               max_threads=DEFAULT_MAX_THREADS,
               avoid_strings=DEFAULT_AVOID_STRINGS,
               search_strings=DEFAULT_SEARCH_STRINGS,
               link_delimiters=DEFAULT_LINK_DELIMITERS):

    self.max_queue_pages = max_queue_pages
    self.max_visited_pages = max_visited_pages
    self.max_parsable_urls = max_parsable_urls
    self.max_threads = max_threads
    self.avoid_strings = avoid_strings
    self.search_strings = search_strings
    self.link_delimiters = link_delimiters

  # Method: dig
  # Description: start a website BFS using a list of continuously updating URLs and
  #              save links containing strings that are being searched.
  #
  def dig(self, starting_urls):
    page_queue = starting_urls
    page_queue_mutex = Lock()
    visited = []
    visited_mutex = Lock()
    files = []
    files_mutex = Lock()
    try:
      logging.warning('[ starting ] Starting multithreaded dig.')
      while (page_queue or threading.active_count()-1 != 0) and len(visited) < self.max_visited_pages:
        desired_threads = min(self.max_threads, len(page_queue))
        while len(page_queue) > self.max_queue_pages:
          page_queue.pop()
        if threading.active_count()-1 < desired_threads:
          threading.Thread(target=self.spider_bfs, args=(page_queue, page_queue_mutex,
                                                         visited,    visited_mutex,
                                                         files,      files_mutex)).start()
        elif threading.active_count()-1 > desired_threads:
          threading.enumerate()[-1].join()
    except KeyboardInterrupt:
      logging.error('Received KeyboardInterrupt in multithreaded spider mode.')
    while threading.active_count() > 1:
      logging.warning('[ finished ] Waiting for '+str(threading.active_count()-1)+' threads...')
      threading.enumerate()[-1].join()
    logging.warning('[ finished ] Found '+str(len(files))+' results.')
    return files

  # Method: spider_bfs
  # Description: grows out the BFS queue.
  #
  def spider_bfs(self,
                 page_queue, page_queue_mutex,
                 visited,    visited_mutex,
                 files,      files_mutex):

    page_queue_mutex.acquire()
    tpage = page_queue.pop()
    page_queue_mutex.release()
    if tpage in visited:
      logging.info(list_to_valuestr([len(page_queue), len(visited), len(files)])
                   +' Skipping visited page.')
      return
    visited_mutex.acquire()
    visited.append(tpage)
    visited_mutex.release()
    logging.info(list_to_valuestr([len(page_queue), len(visited), len(files)])
                 +' Visiting: \x1B[36m'+('...'+tpage[-82:] if len(tpage) > 85 else tpage)+'\x1B[0m')
    self.spider_checkout(tpage, page_queue, page_queue_mutex)
    if any(ftype in tpage for ftype in self.search_strings):
      files_mutex.acquire()
      files.append(tpage)
      files_mutex.release()
      #logging.info('\x1B[32m'+tpage+'\x1B[0m')
    return

  # Method: spider_checkout
  # Description: requests an HTTP/HTTPS page and parses possible links to add to
  #              the queue (currently HTML and CSS only).
  # TODO: maybe use urllib parser instead? Fully rewrite parsing process & is hard to read
  #
  def spider_checkout(self, page, page_queue, page_queue_mutex):
    try:
      current = str(requests.get(page).text)
    except:
      return
    found = []
    filtered_found = set()
    for keyword in self.link_delimiters:
      finding = current.split(keyword[0])
      if len(finding) < 2:
        continue
      for i in range(len(finding)):
        finding[i] = finding[i].split(keyword[1], 1)[0]
      finding.pop(0)
      found.extend(finding)
    page_is_hier = len(page.split('/')) > 3
    for link in found[:self.max_parsable_urls]:
      if any(issue in link[8:] for issue in self.avoid_strings):
        continue
      if link[:8] != 'https://' and link[:7] != 'http://':
        # no leading 'http*://' protocol
        if '//' not in link:
          # no double slashes at all
          if link.count('.') <= 1 and link.count('/') == 0:
            # '*.*'
            filtered_found.add('/'.join(page.split('/')[:-1 if page_is_hier else None]) + '/' + link)
          elif link.count('.') <= 1 and link.count('/') > 0:
            # '*/*.*'
            slashes = link.count('/')+1
            for slash in range(slashes):
              filtered_found.add('/'.join(page.split('/')[:-1 if page_is_hier else None]) + '/' + link.split('/', slashes-slash)[-1])
          elif link.count('..') > 0:
            # ..*
            continue
          else:
            # '*.*.*'
            filtered_found.add('http://' + link)
            filtered_found.add('https://' + link)
        else:
          # '*//*
          filtered_found.add('http://' + link.split('//', 1)[1])
          filtered_found.add('https://' + link.split('//', 1)[1])
      elif link in ('https://', 'http://'):
        # just 'http*://' with nothing attached
        continue
      else:
        # starts with 'http*://' protocol
        if link[8:].count('/') == 0:
          # 'http*://*'
          filtered_found.add(link)
        else:
          # 'http*://*/*'
          slashes = link.count('/')+1-2
          for slash in range(slashes):
            filtered_found.add('http://'+'/'.join(link.split('/')[2:]).rsplit('/', slash)[0])
            filtered_found.add('https://'+'/'.join(link.split('/')[2:]).rsplit('/', slash)[0])
    page_queue_mutex.acquire()
    page_queue.update(filtered_found)
    page_queue_mutex.release()
    return
#
# End of class SmallSpider


# Function: int_to_valuestr
# Description: turns big numbers into cool notation.
#
def int_to_valuestr(value):
  if value < 1000:
    return str(value)
  if value < 1000000:
    return str(round(value/1000, 1))+'k'
  return str(round(value/1000000, 1))+'M'


# Function: list_to_valuestr
# Description: turns multiple big numbers into cool notation.
#
def list_to_valuestr(value_list):
  string = '[ '
  for value in value_list:
    string += int_to_valuestr(value)+' '
  string += ']'
  return string


# Run module directly
# Description: put
#
if __name__ == "__main__":
  if len(sys.argv) < 2:
    sys.exit('\x1B[33mNo arguments.\x1B[0m')
  for arg in sys.argv[1:]:
    if arg[:7] != 'http://' and arg[:8] != 'https://':
      sys.exit('\x1B[33mArguments must begin with protocol.\x1B[0m')
    if arg[-1] == '/':
      sys.exit('\x1B[33mArguments must end without slash.\x1B[0m')

  try:
    logging.basicConfig(format='[%(asctime)s] %(levelname)-8s %(message)s',
                        datefmt='%H%M%S',
                        level=logging.INFO)
    argument_urls = set()
    for arg in sys.argv[1:]:
      argument_urls.add(arg)
    spider = SmallSpider(max_visited_pages=200, max_threads=8)
    try:
      files = spider.dig(argument_urls)
      for result in files:
        logging.info('\x1B[32m'+result+'\x1B[0m')
    except KeyboardInterrupt:
      pass

  except:
    pass
