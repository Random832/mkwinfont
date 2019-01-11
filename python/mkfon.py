#!/usr/bin/python3

# mkwinfont is copyright 2001 Simon Tatham. All rights reserved.
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
########################################################################
#
# Feb 2017 - Updated to Python3.  Added in/ex-leading.
#            ".x" as well as "01".  Other minor changes.  [mj.Jernigan]
#            Could rewrite all the byte handling in a Py3 way,
#            but why bother?
#
########################################################################
# 2019-01-10 Random832
# - Separate the FON support into its own thing
# - Clean up some of the byte handling

import sys
import struct
#import string

def byte(i):
	return struct.pack('<B', i)
def word(i):
	return struct.pack('<H', i)
def dword(i):
	return struct.pack('<L', i)

def frombyte(s, o=0):
	return struct.unpack('<B', s[o:o+1])[0]
def fromword(s, o=0):
	return struct.unpack('<H', s[o:o+2])[0]
def fromdword(s, o=0):
	return struct.unpack('<L', s[o:o+4])[0]
def asciz(s, o):
	i = s.find(b"\0", o)
	if i != -1:
		return s[o:i]
	return s[o:]

# Archive FNT files into a FON file. Do one thing and do it well.
def direntry(f):
	"Return the FONTDIRENTRY, given the data in a .FNT file."
	device = fromdword(f, 0x65)
	face = fromdword(f, 0x69)
	if device == 0:
		devname = b""
	else:
		devname = asciz(f, device)
	facename = asciz(f, face)
	return f[0:0x71] + devname + b"\0" + facename + b"\0"

stubcode = [
  0xBA, 0x0E, 0x00, # mov dx,0xe
  0x0E,             # push cs
  0x1F,             # pop ds
  0xB4, 0x09,       # mov ah,0x9
  0xCD, 0x21,       # int 0x21
  0xB8, 0x01, 0x4C, # mov ax,0x4c01
  0xCD, 0x21        # int 0x21
]
stubmsg = b"This is not a program!\r\nFont library created by mkwinfont.\r\n"

def stub():
	"Create a small MZ executable."
	file = b""
	file = file + b"MZ" + word(0) + word(0)
	file = file + word(0) # no relocations
	file = file + word(4) # 4-para header
	file = file + word(0x10) # 16 extra para for stack
	file = file + word(0xFFFF) # maximum extra paras: LOTS
	file = file + word(0) + word(0x100) # SS:SP = 0000:0100
	file = file + word(0) # no checksum
	file = file + word(0) + word(0) # CS:IP = 0:0, start at beginning
	file = file + word(0x40) # reloc table beyond hdr
	file = file + word(0) # overlay number
	file = file + 4 * word(0) # reserved
	file = file + word(0) + word(0) # OEM id and OEM info
	file = file + 10 * word(0) # reserved
	file = file + dword(0) # offset to NE header
	assert len(file) == 0x40
	for i in stubcode: file = file + byte(i)
	file = file + stubmsg + b"$"
	n = len(file)
	#pages = (n+511) / 512
	pages = (n+511) // 512
	lastpage = n - (pages-1) * 512
	file = file[:2] + word(lastpage) + word(pages) + file[6:]
	# Now assume there will be a NE header. Create it and fix up the
	# offset to it.
	while len(file) % 16: file = file + b"\0"
	file = file[:0x3C] + dword(len(file)) + file[0x40:]
	return file

def fon(name, fonts):
	"Create a .FON font library, given a bunch of .FNT file contents."

	name = bytes(name, encoding="windows-1252")

	# Construct the FONTDIR.
	fontdir = word(len(fonts))
	for i in range(len(fonts)):
		fontdir = fontdir + word(i+1)
		fontdir = fontdir + direntry(fonts[i])

	# The MZ stub.
	stubdata = stub()
	# Non-resident name table should contain a FONTRES line.
	nonres = b"FONTRES 100,96,96 : " + name
	nonres = byte(len(nonres)) + nonres + b"\0\0\0"
	# Resident name table should just contain a module name.
	mname = b""
	for c in name:
		if c in b"0123546789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
			mname = mname + bytes([c])
	res = byte(len(mname)) + mname + b"\0\0\0"
	# Entry table / imported names table should contain a zero word.
	entry = word(0)

	# Compute length of resource table.
	# 12 (2 for the shift count, plus 2 for end-of-table, plus 8 for the
	#    "FONTDIR" resource name), plus
	# 20 for FONTDIR (TYPEINFO and NAMEINFO), plus
	# 8 for font entry TYPEINFO, plus
	# 12 for each font's NAMEINFO 

	# Resources are currently one FONTDIR plus n fonts.
	# TODO: a VERSIONINFO resource would be nice too.
	resrcsize = 12 + 20 + 8 + 12 * len(fonts)
	resrcpad = ((resrcsize + 15) &~ 15) - resrcsize

	# Now position all of this after the NE header.
	p = 0x40        # NE header size
	off_segtable = off_restable = p
	p = p + resrcsize + resrcpad
	off_res = p
	p = p + len(res)
	off_modref = off_import = off_entry = p
	p = p + len(entry)
	off_nonres = p
	p = p + len(nonres)

	pad = ((p+15) &~ 15) - p
	p = p + pad
	q = p + len(stubdata)

	# Now q is file offset where the real resources begin. So we can
	# construct the actual resource table, and the resource data too.
	restable = word(4) # shift count
	resdata = b""
	# The FONTDIR resource.
	restable = restable + word(0x8007) + word(1) + dword(0)
	restable = restable + word((q+len(resdata)) >> 4)
	start = len(resdata)
	resdata = resdata + fontdir
	while len(resdata) % 16: resdata = resdata + b"\0"    
	restable = restable + word((len(resdata)-start) >> 4)
	restable = restable + word(0x0C50) + word(resrcsize-8) + dword(0)
	# The font resources.
	restable = restable + word(0x8008) + word(len(fonts)) + dword(0)
	for i in range(len(fonts)):
		restable = restable + word((q+len(resdata)) >> 4)
		start = len(resdata)
		resdata = resdata + fonts[i]
		while len(resdata) % 16: resdata = resdata + b"\0"    
		restable = restable + word((len(resdata)-start) >> 4)
		restable = restable + word(0x1C30) + word(0x8001 + i) + dword(0)
	# The zero word.
	restable = restable + word(0)
	assert len(restable) == resrcsize - 8
	restable = restable + b"\007FONTDIR"
	restable = restable + b"\0" * resrcpad

	file = stubdata + b"NE" + byte(5) + byte(10)
	file = file + word(off_entry) + word(len(entry))
	file = file + dword(0) # no CRC
	file = file + word(0x8308) # the Mysterious Flags
	file = file + word(0) + word(0) + word(0) # no autodata, no heap, no stk
	file = file + dword(0) + dword(0) # CS:IP == SS:SP == 0
	file = file + word(0) + word(0) # segment table len, modreftable len
	file = file + word(len(nonres))
	file = file + word(off_segtable) + word(off_restable)
	file = file + word(off_res) + word(off_modref) + word(off_import)
	file = file + dword(len(stubdata) + off_nonres)
	file = file + word(0) # no movable entries
	file = file + word(4) # seg align shift count
	file = file + word(0) # no resource segments
	file = file + byte(2) + byte(8) # target OS and more Mysterious Flags
	file = file + word(0) + word(0) + word(0) + word(0x300)

	# Now add in all the other stuff.
	file = file + restable + res + entry + nonres + b"\0" * pad + resdata

	return file

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Combine FNT files into a FON')
    parser.add_argument('fnt', type=str, nargs='+')
    parser.add_argument('-o', '--outfile', type=str, required=True)
    parser.add_argument('-N', '--facename', type=str)

    args = parser.parse_args()
    fnts = []
    if not args.facename:
        facenames = set()
    for fnt in args.fnt:
        data = open(fnt, 'rb').read()
        if not args.facename:
            off = fromdword(data, 0x69)
            facename = asciz(data, off).decode('windows-1252')
            facenames.add(facename)
        fnts.append(data)
        if len(facenames) != 1:
            raise Exception("fonts disagree on face name; specify one with --facename")
        else:
            args.facename, = facenames

    open(args.outfile, 'wb').write(fon(facename, fnts))

if __name__ == '__main__':
    main()
