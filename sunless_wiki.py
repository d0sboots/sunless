#!/usr/bin/python3

"""Utility for editing the Sunless Sea wiki.

This command-line script (usually) produces output on stdout in a format that
can be directly cut-and-pasted to the edit box of pages at
https://sunlesssea.gamepedia.com/. In the usual case where there is existing
content, replace that content entirely, and then use the diff feature to add
back in flavor text that was overwritten.

To run, this requires the following files in the current directory:
* areas.json
* events.json
* qualities.json
* exchanges.json
* tiles.json

The first four come from your savegame directory, see
https://sunlesssea.gamepedia.com/Moding_Guide. The last one needs to be
extracted from the game file resources.assets using a tool like Unity Asset
Bundle Extractor. The name of the asset is "Tiles", Path ID: 1145.
"""

import argparse
import collections
import json
import sys

def SnakeCase(string):
  return ''.join('_' + x if x.isupper() else x.upper()
      for x in string).lstrip('_')

for key in ['Area', 'Availabilities', 'Category', 'ChildBranches', 'Cost', 'Deck',
    'DefaultEvent', 'Description', 'DifficultyScaler', 'DifficultyTestType',
    'Id', 'Image', 'IsSlot', 'LimitedToArea', 'LinkToEvent', 'Name', 'Nature',
    'Ordering', 'ParentGroup', 'Persistent', 'PortData', 'PurchaseQuality',
    'Quality', 'QualitiesRequired', 'RareDefaultEvent', 'RareSuccessEvent',
    'SellPrice', 'Setting', 'SettingIds', 'Shops', 'Subsurface',
    'SuccessEvent', 'SwitchToSetting', 'Tag', 'Teaser', 'Tiles']:
  globals()[SnakeCase(key)] = key

# Used to iterate over the branches
EVENT_TYPES = [SUCCESS_EVENT, DEFAULT_EVENT,
    RARE_SUCCESS_EVENT, RARE_DEFAULT_EVENT]

# These are qualities where increases are shown as red instead of green.
BAD_QUALITIES = {
  102025: 'Terror',
  102024: 'Hunger',
  # All menaces are added dynamically, in InitGlobals()
}

# A map from exchange id to the list of areas the shop is accesible from. (Not
# necessarily all the time.)
SHOP_AREAS = {}

# Id lookup maps for the various lists
AREAS_MAP = {}
QUALITIES_MAP = {}
EVENTS_MAP = {}

# Needed for filtering
LIMBO = 101956

def ForEachBranch(event):
  for branch in event[CHILD_BRANCHES]:
    for x in EVENT_TYPES:
      outcome = branch[x]
      if not outcome:
        continue
      if outcome[CHILD_BRANCHES]:
        raise RuntimeError("Nested branch in id %d: %s" % (event[ID],
          json.dumps(outcome[CHILD_BRANCHES], indent=2)))
      yield outcome

def AddShopInfo(group, area):
  if area[ID] == LIMBO:
    return
  value = SHOP_AREAS[group[ID]]
  if area not in value:
    value.append(area)

def InitGlobals():
  for item in AREAS:
    # Create this key, for the cases where we can't tell if it's on the
    # surface or not. This usually means it's not a port.
    item[SUBSURFACE] = None
    AREAS_MAP[item[ID]] = item
  # Correct a few names that aren't how we want them
  AREAS_MAP[100374][NAME] = 'Venderbight'
  AREAS_MAP[101981][NAME] = 'The Chelonate'
  AREAS_MAP[102000][NAME] = 'Polythreme'
  AREAS_MAP[102960][NAME] = 'The Uttershroom'

  for item in QUALITIES:
    QUALITIES_MAP[item[ID]] = item
    if item[NAME].startswith('Menaces:'):
      BAD_QUALITIES[item[ID]] = item[NAME]

  for event in EVENTS:
    EVENTS_MAP[event[ID]] = event
    event[AREA] = []
  # DFS to create a synthetic list area ids where each area can be found
  for x in EVENTS:
    stack = [x]
    limit = x[LIMITED_TO_AREA]
    if not limit:
      continue
    limit_id = limit[ID]
    while stack:
      event = stack.pop()
      if limit_id in event[AREA]:
        continue
      event[AREA].append(limit_id)
      for outcome in ForEachBranch(event):
        link = outcome[LINK_TO_EVENT]
        if not link:
          continue
        stack.append(EVENTS_MAP[link[ID]])

  settings_map = {}
  for group in EXCHANGES:
    SHOP_AREAS[group[ID]] = []
    for setting in group[SETTING_IDS]:
      settings_map[setting] = group

  # Set up SHOP_AREAS for static shops
  for tile in TILES_DATA:
    entry = tile[TILES]
    if not entry:
      continue
    for port in entry[0][PORT_DATA]:
      area = AREAS_MAP[port[AREA][ID]]
      area[SUBSURFACE] = port[SUBSURFACE]
      setting_id = port[SETTING][ID]
      if setting_id not in settings_map:
        continue
      AddShopInfo(settings_map[setting_id], area)
  # Iterate the events one more time to fill out SHOP_AREAS for shops that
  # change dynamically
  for event in EVENTS:
    for outcome in ForEachBranch(event):
      setting = outcome[SWITCH_TO_SETTING]
      if not setting:
        continue
      group = settings_map[setting[ID]]
      for area_id in event[AREA]:
        AddShopInfo(group, AREAS_MAP[area_id])

def MakeShopList():
  shop_list = []
  for group in EXCHANGES:
    for shop in group[SHOPS]:
      shop[PARENT_GROUP] = group
      shop_list.append(shop)
  return shop_list

def FuzzyLookupItem(name_or_id, lst):
  try:
    idd = int(name_or_id)
    for x in lst:
      if x[ID] == idd:
        return x
    raise RuntimeError('Id %d not found!' % idd)
  except ValueError:
    insensitive = name_or_id.islower()
    matches = []
    for x in lst:
      name = x[NAME] or ''
      if name_or_id == name:
        return x
      if insensitive:
        name = name.lower()
      if name_or_id in name:
        matches.append(x)
    if len(matches) == 1:
      return matches[0]
    if not matches:
      raise RuntimeError('No name containing "%s" found!' % name_or_id)
    raise RuntimeError('Multiple matches for "%s": %s' % (
      name_or_id, [x[NAME] for x in matches]))

def NullWrap(x):
  if x == None:
    return 'null'
  return x

def DumpRawQualities():
  QUALITIES.sort(key = lambda x: x[ID])
  for item in QUALITIES:
    print('* %d: [[%s]] (%s, %s)' % (
      item[ID], item[NAME], item[NATURE], item[CATEGORY]))

def DumpRawEvents():
  EVENTS.sort(key = lambda x: x[ID])
  for item in EVENTS:
    fmt = '* %d: [[%s]] %s| [File:SS %sgaz.png]'
    area = ''
    if item[LIMITED_TO_AREA]:
      area = '(%s) ' % AREAS_MAP[item[LIMITED_TO_AREA][ID]][NAME]
    print(fmt % (item[ID], NullWrap(item[NAME]), area, NullWrap(item[IMAGE])))

def DumpRawShops():
  EXCHANGES.sort(key = lambda x: x[ID])
  for item in EXCHANGES:
    print(json.dumps(item, indent=2))

def QualitiesPage():
  groups = {}
  for item in QUALITIES:
    if item[CATEGORY] not in ['Story', 'Circumstance']:
      continue
    if item[IMAGE] == None:
      continue
    if ':' in item[NAME]:
      parts = item[NAME].split(':', 1)
      groups.setdefault(parts[0], []).append(item)
    else:
      groups.setdefault('Misc', []).append(item)
  misc = groups['Misc']
  del groups['Misc']
  groups_ordered = list(groups.items())
  groups_ordered.sort()
  groups_ordered.append(('Misc', misc))

  print('=List of Qualities=\n')
  for group in groups_ordered:
    print('==%s==' % group[0])
    print('''{| class="ss-table" style="width:100%;"
!style="width:50px;" | Portrait
!style="width:33%;" | Quality
!style="width:50px;" | Portrait
!style="width:33%;" | Quality
!style="width:50px;" | Portrait
!style="width:33%;" | Quality''')
    section = group[1]
    section.sort(key=lambda x:x[NAME])
    for i in range(0, len(section), 3):
      print('|-')
      for j in range(i, min(i + 3, len(section))):
        print('| [[File:SS %ssmall.png|center]]' % section[j][IMAGE])
        print('| [[%s]]' % section[j][NAME])
        print('')
    print('|-\n|}\n')

  print('''{{Navbox qualities}}
[[Category:Sunless Sea journal]]
[[Category:Sunless Sea qualities| ]]''')

def LocationOfShop(idd, abbreviate=True):
  lookup = SHOP_AREAS[idd]
  if len(lookup) == 1:
    return '[[%s]]' % lookup[0][NAME]
  if not lookup:
    return 'Not available in-game'
  if abbreviate:
    return 'Various'
  eligible = sorted('[[%s]]' % x[NAME] for x in lookup)
  return ', '.join(eligible[:-1]) + ', and ' + eligible[-1]

def ShopSortKey(group):
  count = len(SHOP_AREAS[group[ID]])
  if count > 1:
    count = 2
  elif count == 0:
    count = 3
  return (count, LocationOfShop(group[ID]))

def ShopsPage():
  print('==List of Shops==\n')
  EXCHANGES.sort(key=ShopSortKey)
  last_location = None
  for group in EXCHANGES:
    location = LocationOfShop(group[ID])
    if location != last_location:
      print('===%s===' % location)
    last_location = location
    print("'''%s'''" % group[NAME], end='')
    if group[DESCRIPTION]:
      print(': %s' % group[DESCRIPTION])
    else:
      print()
    shops = [x for x in group[SHOPS] if len(x[AVAILABILITIES])]
    num_cols = min(3, len(shops))
    print('{| class="ss-table" style="width:%d%%;"' % (99 * num_cols / 3))
    print(('''!style="width:50px;" | Portrait
!style="width:%d%%;" | Shop
''' % (100 / num_cols)) * num_cols, end='')
    shops.sort(key=lambda x:x[ORDERING])
    for i in range(0, len(shops), 3):
      print('|-')
      for j in range(i, min(i + 3, len(shops))):
        print('| [[File:SS %ssmall.png|center]]' % shops[j][IMAGE])
        print('| [[%s]]' % shops[j][NAME])
        print('')
    print('|-\n|}\n')

  print('''{{Navbox shops}}
[[Category:Sunless Sea gameplay]]''')

def LinkQty(amount, quality, zero_bad=False):
  if amount == 0:
    invert = zero_bad  # By default, zero is good
  else:
    invert = quality[ID] in BAD_QUALITIES
  return '{{link qty|%+d|%s|SS %ssmall.png%s}}' % (
      amount, quality[NAME], quality[IMAGE], '|-' if invert else '')

def WikiShop(shop):
  group = shop[PARENT_GROUP]
  del shop[PARENT_GROUP]
  location = LocationOfShop(group[ID], abbreviate=False)
  print("""{{{{Infobox shops
|image=SS {image}small.png
|category=[[Shops|Shop]]
|part of={group}
|located={location}
|id={id}
}}}}

==Description==
'''{{{{PAGENAME}}}}''' is a shop in {location}.

==Shop Description==""".format(
    image=shop[IMAGE], group=group[NAME],
    location=location, id=shop[ID],
    group_description=group[DESCRIPTION],
    description=shop[DESCRIPTION]))
  shop[AVAILABILITIES].sort(key=lambda x:x[COST])

  if group[DESCRIPTION]:
    print("%s: ''\"%s\"''\n" % (group[NAME], group[DESCRIPTION]))
  if shop[DESCRIPTION]:
    print("{{PAGENAME}}: ''\"%s\"''\n" % shop[DESCRIPTION])
  print('''==Offer==
{| class="ss-table" style="width:100%;"
!style="width:20%;"|Name
!style="width:20%;"|Buy
!style="width:20%;"|Sell
!style="width:40%;"|Notes''')
  for offer in shop[AVAILABILITIES]:
    quality = QUALITIES_MAP[offer[QUALITY][ID]]
    if quality[CATEGORY] == 'Ship':
      continue  # Will appear in Shipyard instead of shop
    purchase_quality = QUALITIES_MAP[offer[PURCHASE_QUALITY][ID]]
    print('|-')
    print('|{{link icon|%s|SS %ssmall.png}}' % (
      quality[NAME], quality[IMAGE]))
    if offer[COST]:
      print('|' + LinkQty(-offer[COST], purchase_quality))
    else:
      print('|')
    print('|' + LinkQty(offer[SELL_PRICE], purchase_quality, zero_bad=True))
    print('|')  # Notes
  print('|-\n|}\n\n{{Navbox shops}}')
  areas = SHOP_AREAS[group[ID]]
  for area in areas:
    print('[[Category: %s shops]]' % area[NAME])
  subsurface = False
  for area in areas:
    subsurface = subsurface or area[SUBSURFACE]
  if subsurface:
    print('[[Category:Zubmariner Content]]')

def PrintCounts(group):
  counts = {}
  for e in group:
    for k, v in e.items():
      if type(v) == list or type(v) == dict:
        v = repr(v)
      counts.setdefault(k, collections.Counter())[v] += 1
  for k, v in counts.items():
    print('"%s": %s' % (k, v.most_common(3)))

def QualitySlice1(x):
  if not x:
    return (IS_SLOT, PERSISTENT, NATURE, CATEGORY, TAG, ID, NAME)
  return (x[IS_SLOT], x[PERSISTENT], x[NATURE], x[CATEGORY], x[TAG] or '', x[ID], x[NAME])

def PrintBySlice(group, func):
  group.sort(key=func)
  result = [func(None)]
  sizes = [0] * (len(result[0]) - 1)
  result += [func(x) for x in group]
  for item in result:
    for i in range(len(item) - 1):
      if len(str(item[i])) > sizes[i]:
        sizes[i] = len(str(item[i]))
  sizes = [min(22, x) for x in sizes]
  fmt = ''.join('%%%ds ' % x for x in sizes) + '%s'
  for item in result:
    print(fmt % item)

if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument('--dump_event',
                      help='Lookup a specific event, by name or id')
  parser.add_argument('--dump_quality',
                      help='Lookup a specific quality, by name or id')
  parser.add_argument('--dump_area',
                      help='Lookup a specific area, by name or id')
  parser.add_argument('--dump_shop',
                      help='Lookup a specific shop, by name or id')
  parser.add_argument('--shop',
                      help='Output wiki text for a shop, looked up by name or id')
  parser.add_argument('--raw_events', action='store_true',
                      help='Output wiki text for a raw dump of all events'
                      '(https://sunlesssea.gamepedia.com/Raw_Dump_(Events))')
  parser.add_argument('--raw_qualities', action='store_true',
                      help='Output wiki text for a raw dump of all qualities'
                      '(https://sunlesssea.gamepedia.com/Raw_Dump_(Qualities))')
  parser.add_argument('--raw_shops', action='store_true',
                      help='Output a raw dump of all shops (Not in wiki format)')
  parser.add_argument('--qualities_page', action='store_true',
                      help='Output wiki text for the Qualities page '
                      '(https://sunlesssea.gamepedia.com/Qualities)')
  parser.add_argument('--shops_page', action='store_true',
                      help='Output wiki text for the Shops page '
                      '(https://sunlesssea.gamepedia.com/Shops)')
  parser.add_argument('--slice', action='store_true',
                      help='Pretty-print *something*, sliced by various fields.')
  args = parser.parse_args()

  print('Reading data... ', end='', flush=True, file=sys.stderr)
  with open('areas.json') as f:
    AREAS = json.load(f)
  with open('events.json') as f:
    EVENTS = json.load(f)
  with open('qualities.json') as f:
    QUALITIES = json.load(f)
  with open('exchanges.json') as f:
    EXCHANGES = json.load(f)
  # This needs to be extracted from the game with something like Unity Asset
  # Bundle Extractor. The file is resources.assets, Name: Tiles, Path ID: 1145
  with open('tiles.json') as f:
    TILES_DATA = json.load(f)

  InitGlobals()
  print('Done!', flush=True, file=sys.stderr)

  try:
    item = None
    if args.dump_event:
      item = FuzzyLookupItem(args.dump_event, EVENTS)
    if args.dump_quality:
      item = FuzzyLookupItem(args.dump_quality, QUALITIES)
    if args.dump_area:
      item = FuzzyLookupItem(args.dump_area, AREAS)
    if args.dump_shop:
      item = FuzzyLookupItem(args.dump_shop, MakeShopList())[PARENT_GROUP]
      for shop in item[SHOPS]:
        del shop[PARENT_GROUP]
    if item:
      json.dump(item, sys.stdout, indent=2)
    else:
      if args.shop:
        WikiShop(FuzzyLookupItem(args.shop, MakeShopList()))
      elif args.slice:
        PrintBySlice(QUALITIES, QualitySlice1)
      elif args.raw_qualities:
        DumpRawQualities()
      elif args.raw_events:
        DumpRawEvents()
      elif args.raw_shops:
        DumpRawShops()
      elif args.qualities_page:
        QualitiesPage()
      elif args.shops_page:
        ShopsPage()
      else:
        print('Nothing to do!', file=sys.stderr)
  except RuntimeError as e:
    print(e, file=sys.stderr)
