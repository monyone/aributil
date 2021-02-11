#!/usr/bin/env python3

import argparse
import sys
import base64

from mpeg2ts.packet import Packet
from mpeg2ts.section import Section
from mpeg2ts.pes import PES
from mpeg2ts.parser import SectionParser, PESParser

if __name__ == "__main__":
  parser = argparse.ArgumentParser(description=('ARIB mpeg2ts unrecognizer'))

  parser.add_argument('-i', '--input', type=argparse.FileType('rb'), nargs='?', default=sys.stdin.buffer)
  parser.add_argument('-o', '--output', type=argparse.FileType('wb'), nargs='?', default=sys.stdout.buffer)
  parser.add_argument('-s', '--SID', type=int)

  args = parser.parse_args()

  PAT_Parser = SectionParser()
  PMT_Parsers = dict()
  PMT_Continuity_Counters = dict()

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

          if (args.SID is None or program_number == args.SID) and (program_map_PID not in PMT_Parsers) and (program_map_PID != 0x10):
            PMT_Parsers[program_map_PID] = SectionParser()
            PMT_Continuity_Counters[program_map_PID] = 0

          begin += 4
      args.output.write(packet)
    elif ts.pid() in PMT_Parsers:
      PMT_Parser = PMT_Parsers[ts.pid()]
      PMT_Parser.push(ts)
      while not PMT_Parser.empty():
        PMT = PMT_Parser.pop()
        if PMT.CRC32() != 0: continue

        STRIPED_PMT = Section(PMT[0:Section.HEADER_SIZE])
        STRIPED_PMT += PMT[Section.HEADER_SIZE + 0: Section.HEADER_SIZE + 2]

        STRIPED_PMT += PMT[Section.HEADER_SIZE + 2: Section.HEADER_SIZE + 4]
        program_info_length = ((PMT[Section.HEADER_SIZE + 2] & 0x0F) << 8) | PMT[Section.HEADER_SIZE + 3]

        STRIPED_PMT += PMT[Section.HEADER_SIZE + 4: Section.HEADER_SIZE + 4 + program_info_length]

        STRIPED_elementary_stream = b''
        begin = Section.HEADER_SIZE + 4 + program_info_length
        while begin < 3 + PMT.section_length() - Section.CRC_SIZE:
          stream_type = PMT[begin + 0]
          elementary_PID = ((PMT[begin + 1] & 0x1F) << 8) | PMT[begin + 2]
          ES_info_length = ((PMT[begin + 3] & 0x0F) << 8) | PMT[begin + 4]

          subtitle_found = False

          descriptor = begin + 5
          while descriptor < (begin + 5 + ES_info_length):
            descriptor_tag = PMT[descriptor + 0]
            descriptor_length = PMT[descriptor + 1]
            if descriptor_tag == 0x52:
              component_tag = PMT[descriptor + 2]
              if stream_type == 0x06 and component_tag == 0x30:
                subtitle_found = True

            descriptor += 2 + descriptor_length

          if subtitle_found:
            STRIPED_elementary_stream += PMT[begin: begin + 3]
            STRIPED_elementary_stream += (0).to_bytes(2, byteorder="big")
          else:
            STRIPED_elementary_stream += PMT[begin: begin + 5 + ES_info_length]

          begin += 5 + ES_info_length
        STRIPED_PMT += STRIPED_elementary_stream

        STRIPED_section_length = len(STRIPED_PMT) + Section.CRC_SIZE - 3
        STRIPED_PMT[1] = (STRIPED_PMT[1] & 0xF0) | ((STRIPED_section_length & 0x0F00) >> 8)
        STRIPED_PMT[2] = (STRIPED_section_length & 0xFF)

        STRIPED_PMT += STRIPED_PMT.CRC32().to_bytes(Section.CRC_SIZE, byteorder="big")

        begin = 0
        while begin < 3 + STRIPED_PMT.section_length():
          PMT_Continuity_Counter = PMT_Continuity_Counters[ts.pid()]
          header  = ts[0].to_bytes(1, byteorder="big")
          header += ((ts[1] & 0xBF) | ((1 if begin == 0 else 0) << 6)).to_bytes(1, byteorder="big")
          header += ts[2].to_bytes(1, byteorder="big")
          header += ((ts[3] & 0xD0) | (PMT_Continuity_Counter & 0x0F)).to_bytes(1, byteorder="big")
          PMT_Continuity_Counter += 1
          PMT_Continuity_Counter &= 0x0F
          PMT_Continuity_Counters[ts.pid()] = PMT_Continuity_Counter

          next = min(3 + STRIPED_PMT.section_length(), begin + (Packet.PACKET_SIZE - Packet.HEADER_SIZE) - (1 if begin == 0 else 0))
          payload = (b'\x00' if begin == 0 else b'') + STRIPED_PMT[begin:next]
          payload += Packet.STUFFING_BYTE * max(0, Packet.PACKET_SIZE - (Packet.HEADER_SIZE + len(payload)))
          args.output.write(header + payload)

          begin = next
    else:
      args.output.write(packet)
