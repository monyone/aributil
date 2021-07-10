#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

from PIL import Image

from mpeg2ts.packet import Packet
from mpeg2ts.section import Section
from mpeg2ts.parser import SectionParser, PESParser
from mpeg2ts.mjd import BCD, MJD_to_YMD

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=('output head time'))

  parser.add_argument('-i', '--input', type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer)
  parser.add_argument('-s', '--SID', type=int, nargs='?')

  args = parser.parse_args()

  PAT_Parser = SectionParser()
  PMT_Parser = SectionParser()
  TOT_Parser = SectionParser()

  PMT_PID = -1
  PCR_PID = -1

  FIRST_PCR = None
  FIRST_TOT = None
  FIRST_TOT_PCR = None

  while args.input:
    while True:
      sync_byte = args.input.read(1)
      if not sync_byte: sys.exit()
      if sync_byte == Packet.SYNC_BYTE: break

    packet = Packet.SYNC_BYTE + args.input.read(Packet.PACKET_SIZE - 1)
    ts = Packet(packet)

    if ts.pid() == 0x00:
      PAT_Parser.push(ts)
      while not PAT_Parser.empty():
        PAT = PAT_Parser.pop()
        if PAT.CRC32() != 0: continue

        begin = Section.HEADER_SIZE
        while begin < 3 + PAT.section_length() - Section.CRC_SIZE:
          program_number = (PAT[begin + 0] << 8) | PAT[begin + 1]
          program_map_PID = ((PAT[begin + 2] & 0x1F) << 8) | PAT[begin + 3]

          if program_number == args.SID:
            PMT_PID = program_map_PID

          begin += 4
    elif ts.pid() == PMT_PID:
      PMT_Parser.push(ts)
      while not PMT_Parser.empty():
        PMT = PMT_Parser.pop()
        if PMT.CRC32() != 0: continue

        PCR_PID = ((PMT[Section.HEADER_SIZE + 0] & 0x1F) << 8) | PMT[Section.HEADER_SIZE + 1]
    elif ts.pid() == PCR_PID:
      if ts.pcr() is None:
        pass
      elif not FIRST_PCR:
        FIRST_PCR = ts.pcr()
      elif FIRST_TOT:
        FIRST_TOT_PCR = ts.pcr()
        delta = timedelta(seconds = (((FIRST_TOT_PCR - FIRST_PCR + 2 ** 33) % (2 ** 33)) / 90000))
        HEAD = FIRST_TOT - delta
        print(HEAD.astimezone(timezone(timedelta(hours=9))))
        break
    elif ts.pid() == 0x14:
      TOT_Parser.push(ts)
      while not TOT_Parser.empty():
        TOT = TOT_Parser.pop()
        if TOT.CRC32() != 0: continue
        if FIRST_TOT: continue

        MJD = (TOT[3 + 0] << 8) + TOT[3 + 1]
        year, month, day = MJD_to_YMD(MJD)
        hour = BCD(TOT[3 + 2])
        min = BCD(TOT[3 + 3])
        sec = BCD(TOT[3 + 4])

        FIRST_TOT = datetime(year, month, day, hour, min, sec)
