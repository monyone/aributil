#!/usr/bin/env python3

import math

class PES:
  HEADER_SIZE = 6

  def __init__(self, payload = b''):
    self.payload = bytearray(payload)

  def __iadd__(self, payload):
    self.payload += payload
    return self

  def __getitem__(self, item):
    return self.payload[item]

  def __setitem__(self, key, value):
    self.payload[key] = value

  def __len__(self):
    return len(self.payload)

  def packet_start_code_prefix(self):
    return (self.payload[0] << 16) | (self.payload[1] << 8) | self.payload[2]

  def stream_id(self):
    return self.payload[3]

  def PES_packet_length(self):
    return (self.payload[4] << 8) | self.payload[5]

  def remains(self):
    if self.PES_packet_length() == 0:
      return math.inf
    else:
      return max(0, (PES.HEADER_SIZE + self.PES_packet_length()) - len(self.payload))

  def fulfilled(self):
    if self.PES_packet_length() == 0:
      return false
    else:
      return len(self.payload) >= PES.HEADER_SIZE + self.PES_packet_length()
