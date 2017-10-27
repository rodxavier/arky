# -*- encoding: utf8 -*-
# © Toons

"""
Usage:
    account link <secret> [<2ndSecret>|-e]
    account unlink
    account status
    account register <username>
    account register 2ndSecret <secret>
    account register escrow <thirdparty>
    account validate <registry>
    account vote [-ud] [<delegate>]
    account send <amount> <address> [<message>]

Options:
-e --escrow  link as escrowed account
-u --up      up vote delegate name folowing
-d --down    down vote delegate name folowing

Subcommands:
    link     : link to account using secret passphrases. If secret passphrases
               contains spaces, it must be enclosed within double quotes
               (ie "secret with spaces").
    unlink   : unlink account.
    status   : show information about linked account.
    register : register linked account as delegate;
               or
               register second signature to linked account;
			   or
               register an escrower using an account address or a publicKey.
    validate : validate transaction from registry.
    vote     : up or down vote delegate(s). <delegate> can be a coma-separated list
               or a valid new-line-separated file list conaining delegate names.
    send     : send ARK amount to address. You can set a 64-char message.
"""

import arky

from .. import cfg
from .. import rest
from .. import util

from . import DATA
from . import input
from . import checkSecondKeys
from . import checkRegisteredTx
from . import floatAmount

import io
import os
import sys


def _send(payload):
	if DATA.escrowed:
		sys.stdout.write("    Writing transaction...\n")
		registry_file = "%s.escrow" % DATA.account["address"]
		registry = util.loadJson(registry_file)
		if registry == {}:
			registry["secondPublicKey"] = DATA.account["secondPublicKey"]
			registry["transactions"] = []
		payload.pop("id", None)
		registry["transactions"].extend([payload])
		util.dumpJson(registry, registry_file)
	else:
		registry_file = "%s.registry" % DATA.account.get("address", "thirdparty")
		registry = util.loadJson(registry_file)
		registry[payload["id"]] = payload
		util.dumpJson(registry, registry_file)
		typ_ = payload["type"]
		sys.stdout.write("    Broadcasting transaction...\n" if typ_ == 0 else \
		                 "    Broadcasting vote...\n" if typ_ == 3 else \
						 "")
		util.prettyPrint(arky.core.sendPayload(payload))
		DATA.daemon = checkRegisteredTx(registry_file, quiet=True)


def _whereami():
	if DATA.account:
		return "account[%s]" % util.shortAddress(DATA.account["publicKey"] if DATA.escrowed else \
	                                             DATA.account["address"])
	else:
		return "account"


def link(param):

	if param["<secret>"]:
		DATA.firstkeys = arky.core.crypto.getKeys(param["<secret>"])
		DATA.account = rest.GET.api.accounts(address=arky.core.crypto.getAddress(DATA.firstkeys["publicKey"])).get("account", {})
	
	if not DATA.account:
		sys.stdout.write("    Accound does not exixts in %s blockchain...\n" % cfg.network)
		unlink(param)
	else:
		if param["<2ndSecret>"]:
			DATA.secondkeys = arky.core.crypto.getKeys(param["<2ndSecret>"])
			DATA.escrowed = False
		elif param["--escrow"]:
			if not DATA.account["secondPublicKey"]:
				sys.stdout.write("    Accound is not escrowed...\n")
				DATA.escrowed = False
			else:
				DATA.escrowed = True
		else:
			DATA.escrowed = False


def unlink(param):
	DATA.account.clear()
	DATA.firstkeys.clear()
	DATA.secondkeys.clear()
	DATA.escrowed = False


def status(param):
	if DATA.account:
		util.prettyPrint(rest.GET.api.accounts(address=DATA.account["address"], returnKey="account"))


def register(param):

	if DATA.account:
		if param["2ndSecret"]:
			secondPublicKey = arky.core.crypto.getKeys(param["<secret>"])["publicKey"]
			if util.askYesOrNo("Register second public key %s ?" % secondPublicKey) \
			   and checkSecondKeys():
				sys.stdout.write("    Broadcasting second secret registration...\n")
				_send(arky.core.crypto.bakeTransaction(
					type=1,
					publicKey=DATA.firstkeys["publicKey"],
					privateKey=DATA.firstkeys["privateKey"],
					secondPrivateKey=DATA.secondkeys.get("privateKey", None),
					asset={"signature":{"publicKey":secondPublicKey}}
				))
		elif param["escrow"]:
			if DATA.account["secondPublicKey"]:
				sys.stdout.write("    This account can not be locked by thirdparty\n")
				return
			resp = rest.GET.api.accounts(address=param["<thirdparty>"])
			if resp["success"]:
				secondPublicKey = resp["account"]["publicKey"]
			else:
				secondPublicKey = arky.core.crypto.getKeys(param["<thirdparty>"])["publicKey"]
			if util.askYesOrNo("Register thirdparty public key %s ?" % secondPublicKey) \
			   and checkSecondKeys():
				sys.stdout.write("    Broadcasting thirdparty registration...\n")
				_send(arky.core.crypto.bakeTransaction(
					type=1,
					publicKey=DATA.firstkeys["publicKey"],
					privateKey=DATA.firstkeys["privateKey"],
					secondPrivateKey=DATA.secondkeys.get("privateKey", None),
					asset={"signature":{"publicKey":secondPublicKey}}
				))
		else:
			username = param["<username>"]
			if util.askYesOrNo("Register %s account as delegate %s ?" % (DATA.account["address"], username)) \
			   and checkSecondKeys():
				sys.stdout.write("    Broadcasting delegate registration...\n")
				_send(arky.core.crypto.bakeTransaction(
					type=2,
					publicKey=DATA.firstkeys["publicKey"],
					privateKey=DATA.firstkeys["privateKey"],
					secondPrivateKey=DATA.secondkeys.get("privateKey", None),
					asset={"delegate":{"username":username, "publicKey":DATA.firstkeys["publicKey"]}}
				))


def validate(param):
	registry = util.loadJson(param["<registry>"])
	if len(registry):
		thirdpartyKeys = arky.core.crypto.getKeys(input("Enter thirdparty passphrase> "))
		if registry["secondPublicKey"] == thirdpartyKeys["publicKey"]:
			items = []
			for tx in registry["transactions"]:
				if tx.get("asset", False):
					items.append("type=%(type)d, asset=%(asset)s" % tx)
				else:
					items.append("type=%(type)d, amount=%(amount)d, recipientId=%(recipientId)s" % tx)
			if not len(items):
				sys.stdout.write("    No transaction found in registry\n")
				return
			choices = util.chooseMultipleItem("Transactions(s) found:", *items)
			if util.askYesOrNo("Validate transactions %s ?" % ",".join([str(i) for i in choices])):
				for idx in choices:
					tx = registry["transactions"][idx-1]
					tx["signSignature"] = arky.core.crypto.getSignature(tx, thirdpartyKeys["privateKey"])
					tx["id"] = arky.core.crypto.getId(tx)
					_send(tx)
				registry["transactions"] = [registry["transactions"][idx] for idx in range(len(registry["transactions"])) \
				                            if idx+1 not in choices]
				util.dumpJson(registry, param["<registry>"])
			else:
				sys.stdout.write("    Validation canceled\n")
		else:
			sys.stdout.write("    Not the valid thirdparty passphrase\n")
	else:
		sys.stdout.write("    Transaction registry not found\n")


def vote(param):
	# if a valid account is linked
	if DATA.account:
		# get account votes
		voted = rest.GET.api.accounts.delegates(address=DATA.account["address"]).get("delegates", [])
		# if usernames is/are given
		if param["<delegate>"]:
			# try to load it from file if a valid path is given
			if os.path.exists(param["<delegate>"]):
				with io.open(param["<delegate>"], "r") as in_:
					usernames = [str(e) for e in in_.read().split() if e != ""]
			else:
				usernames = param["<delegate>"].split(",")

			voted = [d["username"] for d in voted]
			if param["--down"]:
				verb = "Downvote"
				fmt = "-%s"
				to_vote = [username for username in usernames if username in voted]
			else:
				verb = "Upvote"
				fmt = "+%s"
				to_vote = [username for username in usernames if username not in voted]

			if len(to_vote) and util.askYesOrNo("%s %s ?" % (verb, ", ".join(to_vote))) \
							and checkSecondKeys():
				# sys.stdout.write("    Broadcasting vote...\n")
				_send(arky.core.crypto.bakeTransaction(
					type=3,
					recipientId=DATA.account["address"],
					publicKey=DATA.firstkeys["publicKey"],
					privateKey=DATA.firstkeys["privateKey"],
					secondPrivateKey=DATA.secondkeys.get("privateKey", None),
					asset={"votes": [fmt%pk for pk in util.getDelegatesPublicKeys(*to_vote)]}
				))
		elif len(voted):
			util.prettyPrint(dict([d["username"], "%s%%"%d["approval"]] for d in voted))


def send(param):

	if DATA.account:
		amount = floatAmount(param["<amount>"])
		if amount and util.askYesOrNo("Send %(amount).8f %(token)s to %(recipientId)s ?" % \
		                             {"token": cfg.token, "amount": amount, "recipientId": param["<address>"]}) \
		          and checkSecondKeys():
			_send(arky.core.crypto.bakeTransaction(
				amount=amount*100000000,
				recipientId=param["<address>"],
				vendorField=param["<message>"],
				publicKey=DATA.firstkeys["publicKey"],
				privateKey=DATA.firstkeys["privateKey"],
				secondPrivateKey=DATA.secondkeys.get("privateKey", None)
			))
