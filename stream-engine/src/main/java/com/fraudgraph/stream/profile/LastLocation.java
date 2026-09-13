package com.fraudgraph.stream.profile;

/** Value of last-location-store: where and when the user last transacted. */
public record LastLocation(double lat, double lon, long tsMs) {}
