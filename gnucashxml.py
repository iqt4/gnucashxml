# gnucashxml.py --- Parse GNU Cash XML files

# Copyright (C) 2012 Jorgen Schaefer <forcer@forcix.cx>
#           (C) 2017 Christopher Lam

# Author: Jorgen Schaefer <forcer@forcix.cx>
#         Christopher Lam <https://github.com/christopherlam>

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 3
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import decimal
import gzip
from dateutil.parser import parse as parse_date

try:
    from lxml import etree
except ImportError:
    import xml.etree.ElementTree as etree

__version__ = "1.1"


class Book(object):
    """
    A book is the main container for GNU Cash data.

    It doesn't really do anything at all by itself, except to have
    a reference to the accounts, transactions, prices, and commodities.
    """

    def __init__(self, tree, guid, prices=None, transactions=None, root_account=None,
                 accounts=None, commodities=None, slots=None):
        self.tree = tree
        self.guid = guid
        self.prices = prices
        self.transactions = transactions or []
        self.root_account = root_account
        self.accounts = accounts or []
        self.commodities = commodities or []
        self.slots = slots or {}

    def __repr__(self):
        return "<Book {}>".format(self.guid)

    def walk(self):
        return self.root_account.walk()

    def find_account(self, name):
        for account, children, splits in self.walk():
            if account.name == name:
                return account

    def find_guid(self, guid):
        for item in self.accounts + self.transactions:
            if item.guid == guid:
                return item

    def ledger(self):
        outp = []

        for comm in self.commodities:
            outp.append('commodity {}'.format(comm.name))
            outp.append('\tnamespace {}'.format(comm.space))
            outp.append('')

        for account in self.accounts:
            outp.append('account {}'.format(account.fullname()))
            if account.description:
                outp.append('\tnote {}'.format(account.description))
            outp.append('\tcheck commodity == "{}"'.format(account.commodity))
            outp.append('')

        for trn in sorted(self.transactions):
            outp.append('{:%Y/%m/%d} * {}'.format(trn.date, trn.description))
            for spl in trn.splits:
                outp.append('\t{:50} {:12.2f} {} {}'.format(spl.account.fullname(),
                                                            spl.value,
                                                            spl.account.commodity,
                                                            '; ' + spl.memo if spl.memo else ''))
            outp.append('')

        return '\n'.join(outp)


class Commodity(object):
    """
    A commodity is something that's stored in GNU Cash accounts.

    Consists of a name (or id) and a space (namespace).
    """

    # Not implemented
    # - fraction
    # - slots
    def __init__(self, space, symbol, name=None, xcode=None):
        self.space = space
        self.symbol = symbol
        self.name = name
        self.xcode = xcode

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<Commodity {}:{}>".format(self.space, self.symbol)


class Account(object):
    """
    An account is part of a tree structure of accounts and contains splits.
    """

    def __init__(self, name, guid, actype, parent=None,
                 commodity=None, commodity_scu=None,
                 description=None, slots=None):
        self.name = name
        self.guid = guid
        self.actype = actype
        self.description = description
        self.parent = parent
        self.children = []
        self.commodity = commodity
        self.commodity_scu = commodity_scu
        self.splits = []
        self.slots = slots or {}

    def fullname(self):
        if self.parent:
            pfn = self.parent.fullname()
            if pfn:
                return '{}:{}'.format(pfn, self.name)
            else:
                return self.name
        else:
            return ''

    def __repr__(self):
        return "<Account '{}[{}]' {}...>".format(self.name, self.commodity.id, self.guid[:10])

    def walk(self):
        """
        Generate splits in this account tree by walking the tree.

        For each account, it yields a 3-tuple (account, subaccounts, splits).

        You can modify the list of subaccounts, but should not modify
        the list of splits.
        """
        accounts = [self]
        while accounts:
            acc, accounts = accounts[0], accounts[1:]
            children = list(acc.children)
            yield (acc, children, acc.splits)
            accounts.extend(children)

    def find_account(self, name):
        for account, children, splits in self.walk():
            if account.name == name:
                return account

    def get_all_splits(self):
        split_list = []
        for account, children, splits in self.walk():
            split_list.extend(splits)
        return sorted(split_list)

    def __lt__(self, other):
        # For sorted() only
        if isinstance(other, Account):
            return self.fullname() < other.fullname()
        else:
            False


class Transaction(object):
    """
    A transaction is a balanced group of splits.
    """

    def __init__(self, guid=None, currency=None,
                 date=None, date_entered=None,
                 description=None, splits=None,
                 num=None, slots=None):
        self.guid = guid
        self.currency = currency
        self.date = date
        self.post_date = date  # for compatibility with piecash
        self.date_entered = date_entered
        self.description = description
        self.num = num or None
        self.splits = splits or []
        self.slots = slots or {}

    def __repr__(self):
        return "<Transaction on {} '{}' {}...>".format(
            self.date, self.description, self.guid[:6])

    def __lt__(self, other):
        # For sorted() only
        if isinstance(other, Transaction):
            return self.date < other.date
        else:
            False


class Split(object):
    """
    A split is one entry in a transaction.
    """

    def __init__(self, guid=None, memo=None,
                 reconciled_state=None, reconcile_date=None, value=None,
                 quantity=None, account=None, transaction=None, action=None,
                 slots=None):
        self.guid = guid
        self.reconciled_state = reconciled_state
        self.reconcile_date = reconcile_date
        self.value = value
        self.quantity = quantity
        self.account = account
        self.transaction = transaction
        self.action = action
        self.memo = memo
        self.slots = slots

    def __repr__(self):
        return "<Split {} '{}' {} {} {}...>".format(self.transaction.date,
                                                    self.transaction.description,
                                                    self.transaction.currency,
                                                    self.value,
                                                    self.guid[:6])

    def __lt__(self, other):
        # For sorted() only
        if isinstance(other, Split):
            return self.transaction < other.transaction
        else:
            False


class Price(object):
    """
    A price is GNUCASH record of the price of a commodity against a currency
    Consists of date, currency, commodity,  value
    """

    def __init__(self, guid=None, commodity=None, currency=None,
                 date=None, value=None):
        self.guid = guid
        self.commodity = commodity
        self.currency = currency
        self.date = date
        self.value = value

    def __repr__(self):
        return "<Price {}... {:%Y/%m/%d}: {} {}/{} >".format(self.guid[:6],
                                                             self.date,
                                                             self.value,
                                                             self.commodity,
                                                             self.currency)

    def __lt__(self, other):
        # For sorted() only
        if isinstance(other, Price):
            return self.date < other.date
        else:
            False


##################################################################
# XML file parsing

def from_filename(filename):
    """Parse a GNU Cash file and return a Book object."""
    try:
        # try opening with gzip decompression
        return _iterparse(gzip.open(filename, "rb"))
    except IOError:
        # try opening without decompression
        return _iterparse(open(filename, "rb"))


# Implemented:
# - gnc:book
#
# Not implemented:
# - gnc:count-data
#   - This seems to be primarily for integrity checks?
def parse(fobj):
    """Parse GNU Cash XML data from a file object and return a Book object."""
    try:
        tree = lxml.etree.parse(fobj)
    except ParseError:
        raise ValueError("File stream was not a valid GNU Cash v2 XML file")

    root = tree.getroot()
    if root.tag != 'gnc-v2':
        raise ValueError("File stream was not a valid GNU Cash v2 XML file")
    return _book_from_tree(root.find("{http://www.gnucash.org/XML/gnc}book"))


def _iterparse(fobj):

    def _add_guid(elem):
        book.guid = elem.text

    def _add_commodity(c_tree):
        c_space = c_tree.find('./cmdty:space', ns).text
        c_id = c_tree.find('./cmdty:id', ns).text
        commodity = Commodity(c_space, c_id)
        commodity.name = c_tree.find('./cmdty:name', ns)
        e_xcode = c_tree.find('./cmdty:xcode', ns)
        if e_xcode is not None:
            commodity.xcode = e_xcode.text

        commoditiesdict[(c_space, c_id)] = commodity
        book.commodities.append(commodity)

    def _add_account(a_tree):
        act_name = a_tree.find('./act:name', ns).text
        act_id = a_tree.find('./act:id', ns).text
        act_type = a_tree.find('./act:type', ns).text

        account = Account(act_name, act_id, act_type)

        c_tree = a_tree.find('./act:cmdty', ns)
        if c_tree:
            c_space = c_tree.find('./cmdty:space', ns).text
            c_id = c_tree.find('./cmdty:id', ns).text
            account.commodity = commoditiesdict[(c_space, c_id)]

        if act_type != 'ROOT':
            act_parent = a_tree.find('./act:parent', ns).text
            account.parent = accountsdict[act_parent]

        accountsdict[act_id] = account
        book.accounts.append(account)

    def _get_split_from_trn(split_tree, transaction):
        guid = split_tree.find('./split:id', ns).text
        memo = split_tree.find('./split:memo', ns)
        if memo is not None:
            memo = memo.text
        reconciled_state = split_tree.find('./split:reconciled-state', ns).text
        reconcile_date = split_tree.find('./split:reconcile-date/ts:date', ns)
        if reconcile_date is not None:
            reconcile_date = parse_date(reconcile_date.text)
        value = _parse_number(split_tree.find('./split:value', ns).text)
        quantity = _parse_number(split_tree.find('./split:quantity', ns).text)
        account_guid = split_tree.find('./split:account', ns).text
        account = accountsdict[account_guid]
        # slots = _slots_from_tree(split_tree.find(split + "slots"))
        action = split_tree.find('./split:action', ns)
        if action is not None:
            action = action.text

        split = Split(guid=guid,
                      memo=memo,
                      reconciled_state=reconciled_state,
                      reconcile_date=reconcile_date,
                      value=value,
                      quantity=quantity,
                      account=account,
                      transaction=transaction,
                      action=action)

        account.splits.append(split)
        return split

    def _add_transaction(trn_tree):
        guid = trn_tree.find('./trn:id', ns).text
        c_space = trn_tree.find('./trn:currency/cmdty:space', ns).text
        c_symbol = trn_tree.find('./trn:currency/cmdty:id', ns).text
        currency = commoditiesdict[(c_space, c_symbol)]
        date_posted = parse_date(trn_tree.find('./trn:date-posted/ts:date', ns).text)
        date_entered = parse_date(trn_tree.find('./trn:date-entered/ts:date', ns).text)
        description = trn_tree.find('./trn:description', ns).text

        # slots = _slots_from_tree(tree.find(trn + "slots"))
        transaction = Transaction(guid=guid,
                                  currency=currency,
                                  date=date_posted,
                                  date_entered=date_entered,
                                  description=description)

        for split_tree in trn_tree.findall('trn:splits/trn:split', ns):
            split = _get_split_from_trn(split_tree, transaction)
            transaction.splits.append(split)

    tag_function = {
        '{http://www.gnucash.org/XML/book}id': _add_guid,
        '{http://www.gnucash.org/XML/gnc}commodity': _add_commodity,
        '{http://www.gnucash.org/XML/gnc}account': _add_account,
        '{http://www.gnucash.org/XML/gnc}transaction': _add_transaction
    }

    events = ['start-ns', 'start', 'end']
    xml_iter = etree.iterparse(fobj, events=events)
    context = iter(xml_iter)

    commoditiesdict = {}
    accountsdict = {}
    parentguid = {}

    ns = {}
    path = []
    book = None

    for event, elem in context:
        if event == 'start':
            path.append(elem.tag)

            if len(path) == 1 and path[-1] != 'gnc-v2':
                raise ValueError("Not a valid GNU Cash v2 XML file")
            elif len(path) == 2 and path[-1] == '{http://www.gnucash.org/XML/gnc}book':
                book = Book(tree=None, guid=None)

        elif event == 'end':
            if len(path) == 3 and path[-2] == '{http://www.gnucash.org/XML/gnc}book':
                print(path[-1], event, elem.tag)
                try:
                    tag_function[elem.tag](elem)
                except KeyError:
                    pass
                elem.clear()

            elif path[-1] == '{http://www.gnucash.org/XML/gnc}count-data':
                if elem.attrib['{http://www.gnucash.org/XML/cd}type'] == "book" and elem.text != "1":
                    raise ValueError("Only 1 book per XML file allowed")
                else:
                    pass  # TODO count elements of book

            path.pop()

        else:  # event = 'start-ns'
            prefix, uri = elem
            ns[prefix] = uri

    return book

# Implemented:
# - book:id
# - book:slots
# - gnc:commodity
# - gnc:account
# - gnc:transaction
#
# Not implemented:
# - gnc:schedxaction
# - gnc:template-transactions
# - gnc:count-data
#   - This seems to be primarily for integrity checks?
def _book_from_tree(tree):
    guid = tree.find('{http://www.gnucash.org/XML/book}id').text

    # Implemented:
    # - cmdty:space
    # - cmdty:id => Symbol
    # - cmdty:name
    # - cmdty:xcode => optional, e.g. ISIN/WKN
    #
    # Not implemented:
    # - cmdty:get_quotes => unknown, empty, optional
    # - cmdty:quote_tz => unknown, empty, optional
    # - cmdty:source => text, optional, e.g. "currency"
    # - cmdty:fraction => optional, e.g. "1"
    def _commodity_from_tree(tree):
        space = tree.find('{http://www.gnucash.org/XML/cmdty}space').text
        id = tree.find('{http://www.gnucash.org/XML/cmdty}id').text
        commodity = Commodity(space=space, id=id)
        try:
            commodity.name = tree.find('{http://www.gnucash.org/XML/cmdty}name').text
        except AttributeError:
            pass

        try:
            commodity.xcode = tree.find('{http://www.gnucash.org/XML/cmdty}xcode').text
        except AttributeError:
            pass

        return commodity

    commodities = []  # This will store the Gnucash root list of commodities
    for child in tree.findall('{http://www.gnucash.org/XML/gnc}commodity'):
        commodity = _commodity_from_tree(child)
        commodities.append(commodity)

    # Map unique combination of namespace/symbol to instance of Commodity
    commoditydict = {(c.space, c.symbol): c for c in commodities}

    # Implemented:
    # - price
    # - price:guid
    # - price:commodity
    # - price:currency
    # - price:date
    # - price:value
    def _price_from_tree(tree):
        price = '{http://www.gnucash.org/XML/price}'
        cmdty = '{http://www.gnucash.org/XML/cmdty}'
        ts = "{http://www.gnucash.org/XML/ts}"

        guid = tree.find(price + 'id').text
        value = _parse_number(tree.find(price + 'value').text)
        date = parse_date(tree.find(price + 'time/' + ts + 'date').text)

        currency_space = tree.find(price + "currency/" + cmdty + "space").text
        currency_id = tree.find(price + "currency/" + cmdty + "id").text
        # pricedb may contain currencies not part of the commodities root list
        currency = commoditydict.setdefault((currency_space, currency_id),
                                            Commodity(space=currency_space, id=currency_id))

        commodity_space = tree.find(price + "commodity/" + cmdty + "space").text
        commodity_id = tree.find(price + "commodity/" + cmdty + "id").text
        commodity = commoditydict[(commodity_space, commodity_id)]

        return Price(guid=guid,
                     commodity=commodity,
                     date=date,
                     value=value,
                     currency=currency)

    prices = []
    t = tree.find('{http://www.gnucash.org/XML/gnc}pricedb')
    if t is not None:
        for child in t.findall('price'):
            price = _price_from_tree(child)
            prices.append(price)

    root_account = None
    accounts = []
    accountdict = {}
    parentdict = {}

    for child in tree.findall('{http://www.gnucash.org/XML/gnc}account'):
        parent_guid, acc = _account_from_tree(child, commoditydict)
        if acc.actype == 'ROOT':
            root_account = acc
        accountdict[acc.guid] = acc
        parentdict[acc.guid] = parent_guid
    for acc in list(accountdict.values()):
        if acc.parent is None and acc.actype != 'ROOT':
            parent = accountdict[parentdict[acc.guid]]
            acc.parent = parent
            parent.children.append(acc)
            accounts.append(acc)

    transactions = []
    for child in tree.findall('{http://www.gnucash.org/XML/gnc}'
                              'transaction'):
        transactions.append(_transaction_from_tree(child,
                                                   accountdict,
                                                   commoditydict))

    slots = _slots_from_tree(
        tree.find('{http://www.gnucash.org/XML/book}slots'))
    return Book(tree=tree,
                guid=guid,
                prices=prices,
                transactions=transactions,
                root_account=root_account,
                accounts=accounts,
                commodities=commodities,
                slots=slots)


# Implemented:
# - act:name
# - act:id
# - act:type
# - act:description
# - act:commodity
# - act:commodity-scu
# - act:parent
# - act:slots
def _account_from_tree(tree, commoditydict):
    act = '{http://www.gnucash.org/XML/act}'
    cmdty = '{http://www.gnucash.org/XML/cmdty}'

    name = tree.find(act + 'name').text
    guid = tree.find(act + 'id').text
    actype = tree.find(act + 'type').text
    description = tree.find(act + "description")
    if description is not None:
        description = description.text
    slots = _slots_from_tree(tree.find(act + 'slots'))
    if actype == 'ROOT':
        parent_guid = None
        commodity = None
        commodity_scu = None
    else:
        parent_guid = tree.find(act + 'parent').text
        commodity_space = tree.find(act + 'commodity/' +
                                    cmdty + 'space').text
        commodity_name = tree.find(act + 'commodity/' +
                                   cmdty + 'id').text
        commodity_scu = tree.find(act + 'commodity-scu').text
        commodity = commoditydict[(commodity_space, commodity_name)]
    return parent_guid, Account(name=name,
                                description=description,
                                guid=guid,
                                actype=actype,
                                commodity=commodity,
                                commodity_scu=commodity_scu,
                                slots=slots)


# Implemented:
# - trn:id
# - trn:currency
# - trn:date-posted
# - trn:date-entered
# - trn:description
# - trn:splits / trn:split
# - trn:slots
def _transaction_from_tree(tree, accountdict, commoditydict):
    trn = '{http://www.gnucash.org/XML/trn}'
    cmdty = '{http://www.gnucash.org/XML/cmdty}'
    ts = '{http://www.gnucash.org/XML/ts}'
    split = '{http://www.gnucash.org/XML/split}'

    guid = tree.find(trn + "id").text
    currency_space = tree.find(trn + "currency/" +
                               cmdty + "space").text
    currency_name = tree.find(trn + "currency/" +
                              cmdty + "id").text
    currency = commoditydict[(currency_space, currency_name)]
    date = parse_date(tree.find(trn + "date-posted/" +
                                ts + "date").text)
    date_entered = parse_date(tree.find(trn + "date-entered/" +
                                        ts + "date").text)
    description = tree.find(trn + "description").text

    # rarely used
    num = tree.find(trn + "num")
    if num is not None:
        num = num.text

    slots = _slots_from_tree(tree.find(trn + "slots"))
    transaction = Transaction(guid=guid,
                              currency=currency,
                              date=date,
                              date_entered=date_entered,
                              description=description,
                              num=num,
                              slots=slots)

    for subtree in tree.findall(trn + "splits/" + trn + "split"):
        split = _split_from_tree(subtree, accountdict, transaction)
        transaction.splits.append(split)

    return transaction


# Implemented:
# - split:id
# - split:memo
# - split:reconciled-state
# - split:reconcile-date
# - split:value
# - split:quantity
# - split:account
# - split:slots
def _split_from_tree(tree, accountdict, transaction):
    split = '{http://www.gnucash.org/XML/split}'
    ts = "{http://www.gnucash.org/XML/ts}"

    guid = tree.find(split + "id").text
    memo = tree.find(split + "memo")
    if memo is not None:
        memo = memo.text
    reconciled_state = tree.find(split + "reconciled-state").text
    reconcile_date = tree.find(split + "reconcile-date/" + ts + "date")
    if reconcile_date is not None:
        reconcile_date = parse_date(reconcile_date.text)
    value = _parse_number(tree.find(split + "value").text)
    quantity = _parse_number(tree.find(split + "quantity").text)
    account_guid = tree.find(split + "account").text
    account = accountdict[account_guid]
    slots = _slots_from_tree(tree.find(split + "slots"))
    action = tree.find(split + "action")
    if action is not None:
        action = action.text

    split = Split(guid=guid,
                  memo=memo,
                  reconciled_state=reconciled_state,
                  reconcile_date=reconcile_date,
                  value=value,
                  quantity=quantity,
                  account=account,
                  transaction=transaction,
                  action=action,
                  slots=slots)
    account.splits.append(split)
    return split


# Implemented:
# - slot
# - slot:key
# - slot:value
# - ts:date
# - gdate
# - list
def _slots_from_tree(tree):
    if tree is None:
        return {}
    slot = "{http://www.gnucash.org/XML/slot}"
    ts = "{http://www.gnucash.org/XML/ts}"
    slots = {}
    for elt in tree.findall("slot"):
        key = elt.find(slot + "key").text
        value = elt.find(slot + "value")
        type_ = value.get('type', 'string')
        if type_ in ('integer', 'double'):
            slots[key] = int(value.text)
        elif type_ == 'numeric':
            slots[key] = _parse_number(value.text)
        elif type_ in ('string', 'guid'):
            slots[key] = value.text
        elif type_ == 'gdate':
            slots[key] = parse_date(value.find("gdate").text)
        elif type_ == 'timespec':
            slots[key] = parse_date(value.find(ts + "date").text)
        elif type_ == 'frame':
            slots[key] = _slots_from_tree(value)
        elif type_ == 'list':
            slots[key] = [_slots_from_tree(lelt) for lelt in value.findall(slot + "value")]
        else:
            raise RuntimeError("Unknown slot type {}".format(type_))
    return slots


def _parse_number(numstring):
    num, denum = numstring.split("/")
    return decimal.Decimal(num) / decimal.Decimal(denum)
