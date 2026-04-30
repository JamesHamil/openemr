<?php

// OpenEMR database config for Railway.
// Values are resolved at runtime so secrets are not baked into the image.

$host   = getenv('MYSQL_HOST') ?: 'localhost';
$port   = getenv('MYSQL_PORT') ?: '3306';
$login  = getenv('MYSQL_USER') ?: 'openemr';
$pass   = getenv('MYSQL_PASS') ?: 'openemr';
$dbase  = getenv('MYSQL_DATABASE') ?: 'openemr';

$sqlconf = [];
global $sqlconf;
$sqlconf["host"]= $host;
$sqlconf["port"] = $port;
$sqlconf["login"] = $login;
$sqlconf["pass"] = $pass;
$sqlconf["dbase"] = $dbase;

//////////////////////////
//////////////////////////
//////////////////////////
//////DO NOT TOUCH THIS///
$config = 1; /////////////
//////////////////////////
//////////////////////////
//////////////////////////
