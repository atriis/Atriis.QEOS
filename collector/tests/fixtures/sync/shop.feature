Feature: Shop
  Used by CI's collector-action job: command import-features sends this file to the stand-in QEOS.

  Scenario: Opens the shop
    Given the shop is open
    Then the door is open
