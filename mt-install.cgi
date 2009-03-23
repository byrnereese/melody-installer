#!/usr/bin/perl -w
#
# Copyright 2009, Byrne Reese.
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#
=head1 NAME

mt-install.cgi - Simple, fast and bullet proof Open Melody installer.

=head1 DESCRIPTION

This "simple" CGI application makes installing Movable Type and Open
Melody as simple as:

1. Upload one file to web server.

2. Follow on screen instructions.

And that's it. The installer automatically detects what configuration
is best for your system, and if it encounters difficulty will attempt
to make corrections automatically.

=head1 PROCESS

1. Prompt the user for information about their server (with good  
guesses as a default): docroot path, base url, cgi-bin path.

2. Check to see what installation options are available and possible:

     a) install all of OM into a cgi-bin directory
     b) install all of OM into a ExecCGI enabled directory in your docroot
     c) install app files into cgi-bin and static files into docroot

3. Prompt user to select an installation option. For those options  
which are not possible, due to permission or web server constraints,  
the user will be given a link to learn precisely what they need to do  
to resolve the conflict.

4. Prompt user to specify where they want OM to be installed  
specifically.

5. Check the server for installed prerequisites. If any core prereqs  
are missing, block. If any optional prereqs are missing display user a  
list of features that will not be available. Give user the option to  
attempt to install missing prerequisites into the extlib directory of  
OM. If there is a failure, let them know and give them instructions or  
even an email they can send to their hosting provider detailing what  
needs to be done.

6. If everything checks out, then download OM. If perl possesses the  
ability to unzip an archive than a single zip will be downloaded and  
unzipped into the designated directory. If such an ability does not  
exist, attempt to download and install Archive::Extract. If that  
fails, then download each file independently and put it in proper place.

7. Download manifest from server. Manifest will include CRC values.  
Perform CRC check on ALL installed files. Error on any failure.  
Attempt to re-download any missing files.

8. Collect DB connection info. Verify that they are correct.

9. Check to see if Fast CGI is possible.

9. Write user's mt-config.cgi file (with fcgi scripts setup if  
allowable).

10. Attempt to harden server directories:

     a) make support directory writable
     b) make other scripts and files unwritable by group

11. Attempt to setup a crontab entry for run-periodic-tasks? Should I  
do this?

12. Finish - tell user what they need to do to secure their server.  
Offer to send them instructions via email.

13. Kick user into standard OM/MT setup wizard to setup first account.

=head1 LICENSE

This program is licensed under the GPL v3.

=head1 AUTHOR

Byrne Reese <byrne@majordojo.com>

=cut

use strict;
use Cwd;
use CGI qw/:standard/;
use LWP::UserAgent;
use File::Spec;
use File::Path;
use File::Copy qw/ copy /;
use File::Temp qw/ tempfile tempdir /;

use constant VERSION   => 0.1;
use constant DEBUG     => 1;
use constant TEST_FILE => 'test.html';
use constant OM_DOWNLOAD_URL 
    => 'http://www.movabletype.org/downloads/stable/MTOS-4.25-en.zip';
use constant ARCHIVE_EXTRACT_URL
    => 'http://cpansearch.perl.org/src/KANE/Archive-Extract-0.30/lib/Archive/Extract.pm';
use constant IPC_CMD_URL
    => 'http://cpansearch.perl.org/src/KANE/IPC-Cmd-0.42/lib/IPC/Cmd.pm';
use constant PARAMS_CHECK_URL
    => 'http://cpansearch.perl.org/src/KANE/Params-Check-0.26/lib/Params/Check.pm';
use constant MODULE_LOAD_COND_URL 
    => 'http://cpansearch.perl.org/src/KANE/Module-Load-Conditional-0.30/lib/Module/Load/Conditional.pm';
use constant MODULE_LOAD_URL
    => 'http://cpansearch.perl.org/src/KANE/Module-Load-0.16/lib/Module/Load.pm';

my $TYPE      = param('type');
my $FOLDER    = param('folder');
my $MTSTATIC  = param('mtstatic');
my $DOCROOT   = param('docroot');
my $BASEURL   = param('baseurl');
my $CGIBIN    = param('cgibin');
my $CGIBINURL = param('cgibinurl');

my @CORE_REQ = (
    [ 'CGI', 0, 1, 'CGI is required for all Movable Type application functionality.' ],
    [ 'Image::Size', 0, 1, 'Image::Size is required for file uploads (to determine the size of uploaded images in many different formats).' ],
    [ 'File::Spec', 0.8, 1, 'File::Spec is required for path manipulation across operating systems.' ],
    [ 'CGI::Cookie', 0, 1, 'CGI::Cookie is required for cookie authentication.' ],
);

my @CORE_DATA = (
    [ 'DBI', 1.21, 0, 'DBI is required to store data in database.' ],
    [ 'DBD::mysql', 0, 0, 'DBI and DBD::mysql are required if you want to use the MySQL database backend.' ],
);

my @CORE_OPT = (
    # Feature: HTML encoding
    [ 'HTML::Entities', 0, 0, 'HTML::Entities is needed to encode some characters, but this feature can be turned off using the NoHTMLEntities option in the configuration file.' ],
    # Feature: TrackBack
    [ 'LWP::UserAgent', 0, 0, 'LWP::UserAgent is optional; It is needed if you wish to use the TrackBack system, the weblogs.com ping, or the MT Recently Updated ping.' ],
    # Feature: TrackBack
    [ 'HTML::Parser', 0, 0, 'HTML::Parser is optional; It is needed if you wish to use the TrackBack system, the weblogs.com ping, or the MT Recently Updated ping.' ],
    # Feature: XML-RPC
    [ 'SOAP::Lite', 0.50, 0, 'SOAP::Lite is optional; It is needed if you wish to use the MT XML-RPC server implementation.' ],
    # Feature: Upload file overwrite
    [ 'File::Temp', 0, 0, 'File::Temp is optional; It is needed if you would like to be able to overwrite existing files when you upload.' ],
    # Feature: Publish Queue
    [ 'Scalar::Util', 0, 1, 'Scalar::Util is optional; It is needed if you want to use the Publish Queue feature.'],
    [ 'List::Util', 0, 1, 'List::Util is optional; It is needed if you want to use the Publish Queue feature.'],

    # Feature: Thumbnails
    [ 'Image::Magick', 0, 0, 'Image::Magick is optional; It is needed if you would like to be able to create thumbnails of uploaded images.' ],

    # Feature: Some MT Plugins
    [ 'Storable', 0, 0, 'Storable is optional; it is required by certain MT plugins available from third parties.'],

    # Feature: High performant comment authentication
    [ 'Crypt::DSA', 0, 0, 'Crypt::DSA is optional; if it is installed, comment registration sign-ins will be accelerated.'],

    # Feature: Comment Registration
    [ 'MIME::Base64', 0, 0, 'MIME::Base64 is required in order to enable comment registration.'],

    # Feature: AtomPub
    [ 'XML::Atom', 0, 0, 'XML::Atom is required in order to use the Atom API.'],

    # Feature: Memcache
    [ 'Cache::Memcached', 0, 0, 'Cache::Memcached and memcached server/daemon is required in order to use memcached as caching mechanism used by Movable Type.'],

    # Feature: Backup/Restore
    [ 'Archive::Tar', 0, 0, 'Archive::Tar is required in order to archive files in backup/restore operation.'],
    [ 'IO::Compress::Gzip', 0, 0, 'IO::Compress::Gzip is required in order to compress files in backup/restore operation.'],
    [ 'IO::Uncompress::Gunzip', 0, 0, 'IO::Uncompress::Gunzip is required in order to decompress files in backup/restore operation.'],
    [ 'Archive::Zip', 0, 0, 'Archive::Zip is required in order to archive files in backup/restore operation.'],
    [ 'XML::SAX', 0, 0, 'XML::SAX and/or its dependencies is required in order to restore.'],

    # OpenID
    [ 'Digest::SHA1', 0, 0, 'Digest::SHA1 and its dependencies are required in order to allow commenters to be authenticated by OpenID providers including Vox and LiveJournal.'],

    # SMTP
    [ 'Mail::Sendmail', 0, 0, 'Mail::Sendmail is required for sending mail via SMTP Server.'],

    # mt:if
    [ 'Safe', 0, 0, 'This module is used in test attribute of MTIf conditional tag.'],

    # Markdown
    [ 'Digest::MD5', 0, 0, 'This module is used by the Markdown text filter.'],

    # Search
    [ 'Text::Balanced', 0, 0, 'This module is required in mt-search.cgi if you are running Movable Type on Perl older than Perl 5.8.' ],

    # FastCGI
    [ 'FCGI', 0, 0, '' ],
);


print_header();
main();
print_footer();

sub is_cgibin_writable {
   if (!-w $CGIBIN) {
	chmod 0775, $CGIBIN;
	if (!-w $CGIBIN) { 
	    return 0; 
	}
    }
    return 1;
}

sub is_docroot_writable {
   my $dir = $DOCROOT;
#   debug("docroot is $DOCROOT");
   if (!-w $DOCROOT) {
	chmod 0775, $DOCROOT;
	if (!-w $DOCROOT) { 
	    return 0; 
	}
    }
    return 1;
}

sub permissions_check {
    my $dir = getcwd;
    print "<p>Is $dir writable? ";
    if (!-w $dir) {
	debug("$dir is not writable. Try again.");
	# Attempt to fix
	chmod 0775, $dir;
	if (!-w $dir) { 
	    debug("Nope, still not writable.");
	    print "<p>This is what you do to fix your permissions problem.</p>";
	    return 0; 
	}
    }
    debug("$dir is writable");
    return 1;
}

sub prerequisites_check {
    for my $list (\@CORE_REQ, \@CORE_DATA, \@CORE_OPT) {
	my $data = ($list == \@CORE_DATA);
	my $req = ($list == \@CORE_REQ);
	for my $ref (@$list) {
	    my($mod, $ver, $required, $desc) = @$ref;
	    if ('CODE' eq ref($desc)) {
		$desc = $desc->();
	    }
	    eval("use $mod" . ($ver ? " $ver;" : ";"));
	    if ($@) {
		debug("$mod is NOT installed.");
	    } else {
#		debug("$mod is installed.");
	    }
	}
    }
}

sub download_dep {
    my ($libdir, $url) = @_;
    my ($dir) = ($url =~ /lib\/(.*)$/);
    my @parts = split('/',$dir);
    my $file = pop @parts;
    $dir = File::Spec->catdir( $libdir, @parts);
    #debug("Making dir $dir");
    mkpath($dir);
    if (!-e $dir) {
	debug("Could not create $dir");
	return 0;
    } 
    debug("Downloading $file into $dir");
    my $down = File::Download->new({ outfile => $dir });
    $down->download($url);
}

sub download_openmelody {
    eval 'use Archive::Extract';
    $Archive::Extract::DEBUG = 1;
    my $dir = make_tmpdir();
    if ($@) {
	# download each file separately
	debug("Um... Archive::Extract is not installed.");
	my $extlib = File::Spec->catdir( $dir, 'extlib' );
	download_dep( $extlib, ARCHIVE_EXTRACT_URL );
	download_dep( $extlib, IPC_CMD_URL );
	download_dep( $extlib, PARAMS_CHECK_URL );
	download_dep( $extlib, MODULE_LOAD_COND_URL );
	download_dep( $extlib, MODULE_LOAD_URL );

	push @INC, $extlib;
#	print "<p>INC is now " . join("<br>",@INC)."</p>";
	eval 'use Archive::Extract';
	if ($@) {
	    debug("Attempt to install and use Archive Extract failed: $@");
	    return 0;
	}
    }
    debug("Saving Open Melody into $dir");
    my $down = File::Download->new({
	overwrite => 1,
	outfile => $dir,
    });
    debug("Downloading: " . OM_DOWNLOAD_URL);
    $down->download(OM_DOWNLOAD_URL);
#    copy('/Users/breese/Sites/mt-install/MTOS-4.24-en.zip',$dir);
#    $down->saved(File::Spec->catfile($dir,'MTOS-4.24-en.zip'));
    debug("Downloaded: " . $down->saved);
    # unpack archive
    my $archive = Archive::Extract->new(
	archive => $down->saved,
    );
    my $ok = $archive->extract(
	to => $dir 
    );
    if ($ok) {
	print "<p>Unarchive successful! An unpacked MT lives in: ".$archive->extract_path."</p>";
    } else {
	print "<p>FAIL. Could not unpack into $dir</p>";
	return;
    }
#    my ($mtdir) = ($down->saved =~ /([^\/]*)\.zip/);
    my ($mtdir) = ($archive->extract_path =~ /([^\/]*)$/);
    debug("root = $mtdir");
    my $files = $archive->files;
    foreach my $file (@$files) {
#	debug("file = $file");
	my $dest = $file;
	$dest =~ s/^$mtdir\/?//;
	my $orig = File::Spec->catfile($archive->extract_path, $dest);
#	next unless -e $orig;
	if ($TYPE == 1) {
	    # all in cgi-bin
	    $dest = File::Spec->catfile($CGIBIN, $FOLDER, $dest);
	} elsif ($TYPE == 2) {
	    # all in docroot
	    $dest = File::Spec->catfile($DOCROOT, $FOLDER, $dest);
	} elsif ($TYPE == 3) {
	    # static in docroot
	    if ($dest =~ /^mt-static/) { 
		debug("Installing static file");
		$dest = File::Spec->catfile($DOCROOT, $dest);
	    } else {
		debug("Installing application file");
		$dest = File::Spec->catfile($CGIBIN, $FOLDER, $dest);
	    }
	} else {
	    # this should never happen
	}
	if (-d $orig) {
	    debug("Making the directory $dest");
	    mkpath($dest);
	} elsif (-f $orig) {
	    debug("Intalling $orig into $dest");
	    copy($orig,$dest);
	    chmod 0755, $dest if ($orig =~ /\.cgi$/);
	} else {
	    debug("Something weird happened when copying $orig. Its not a file for directory.");
	}
    }
}

sub unpack_openmelody {

}

sub make_tmpdir {
    my $dir = tempdir( );
    chmod 0775, $dir;
#    return "/tmp/y9e1wtwfPU";
    return $dir;
}

sub check_htaccess_and_cgi {
    my $tmpdir = 'tmp_' . int(rand(1000000));
    my $dir = File::Spec->catdir($DOCROOT , $tmpdir);
#    debug("Making $dir");
    mkdir($dir);
    my $htaccess = File::Spec->catfile($dir, '.htaccess');
#    debug("Creating $htaccess");
    open HTACCESS, ">$htaccess";
    print HTACCESS q{
Options +ExecCGI +Includes
AddHandler cgi-script .cgi 
    };
    close HTACCESS;
    my $cgi = File::Spec->catfile($dir, 'test.cgi');
#    debug("Creating $cgi");
    open CGI, ">$cgi";
    print CGI q{#!/usr/bin/perl
print "Content-type: text/plain\n\n";
print "ok";
    };
    close CGI;
    chmod 0775, $dir;
    chmod 0775, $cgi;
    my $url = $BASEURL . File::Spec->catfile($tmpdir,'test.cgi');
    my $res = _getfile($url);
    if ($res->is_success) {
	if ($res->content ne 'ok') {
#	    debug("Contents of test file are incorrect: ".$res->content);
	    return 0;
	} 
    } else {
#	debug("Could not get test file.");
	return 0;
    }
    rmtree($dir);
    return 1;
}

sub docroot_can_serve_cgi {
    return 1;
}

sub prompt_for_mthome {
    my $Q = new CGI;
    print qq{
<script type="text/javascript">
var cgibin = "$CGIBIN";
var baseurl = "$BASEURL";
}.q{
$(document).ready(function(){
  $('#folder').keypress(function() {
    var folder = $('#folder').val();
    $('#mthome').val( cgibin + folder + "/mt.cgi"); 
    $('#mtstatic').val( baseurl + folder + "/mt-static/"); 
  });
  $('.install-type').click(function() {
    var id = $(this).attr('id');
    $('.folder').fadeOut('fast',function() {
      if (id.toString() == "type1") {
        $('#folder-mthome.folder').fadeIn('fast');
      } else if (id == "type2") {
        $('#folder-docroot').fadeIn('fast');
      } else if (id == "type3") {
        $('#folder-mthome').fadeIn('fast');
        $('#folder-mtstatic').fadeIn('fast');
      } else {
        alert("this shouldn't happen");
      }
    });
  });
  $('.impossible input').attr('disabled',true);
  $('.install_opt li').each(function(i,e){ 
     if ($("#" + this.id + ' input').attr('disabled') != true) {
       $('#' + this.id + ' input').attr('checked', true);
       return;
     }
  });
});
</script>
    };
    print q{<form action="mt-install.cgi">};
    print q{  <h2>Time to pick a folder name</h2>};
    print q{  <p>Give the folder you are going to Open Melody a name:</p>};
    print q{  <ul class="folder-name">};
    print q{    <li class="pkg"><label>Folder: <input type="text" id="folder" name="folder" value="mt" size="40" /></label></li>};
    print q{  </ul>};

    my ($can_one,$can_two,$can_three) = check_for_available_install_options();
    print qq{  <input type="hidden" name="docroot" value="$DOCROOT" />};
    print qq{  <input type="hidden" name="cgibin" value="$CGIBIN" />};
    print qq{  <input type="hidden" name="mtstatic" value="$MTSTATIC" />};

   print q{  <h2>And an install option</h2>};
    print q{  <ul class="install_opt">};
    print q{    <li id="type1" class="install-type pkg }.($can_one ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="1" /> Install all of Open Melody in cgi-bin</label> }.(!$can_one ? '<a href="#">Fix me</a>' : '').q{</li>};
    print q{    <li id="type2" class="install-type pkg }.($can_two ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="2" /> Install all of Open Melody in document root</label> }.(!$can_two ? '<a href="#">Fix me</a>' : '').q{</li>};
    print q{    <li id="type3" class="install-type pkg }.($can_three ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="3" /> Install app files in cgi-bin, and static files in document root</label> }.(!$can_three ? '<a href="#">Fix me</a>' : '').q{</li>};
    print q{  </ul>};
    print q{  <ul class="folder">};
     print qq{    <li id="folder-mthome" class="pkg wrap folder"><label for="mthome">URL to Open Melody Admin:</label><input type="text" id="mthome" name="mthome" size="40" value="${CGIBINURL}mt/mt.cgi" /></li>};
    print qq{    <li id="folder-mtstatic" class="pkg wrap folder"><label for="mtstatic">URL to Static Content:</label><input type="text" id="mtstatic" name="mtstatic" size="40" value="${BASEURL}mt-static/" /></li>};
    print qq{    <li id="folder-docroot" class="pkg wrap folder"><label for="docroot">URL to Open Melody:</label><input type="text" id="mtstatic" name="mtstatic" size="40" value="${BASEURL}mt/mt.cgi" /></li>};
    print q{  </ul>};
    print q{  <p><input type="submit" name="submit" value="Next" /></p>};
    print q{</form>};
}

sub prompt_for_file_paths {
    my $Q = new CGI;
    print qq{
<script type="text/javascript">
var cgibin = "$CGIBIN";
var baseurl = "$BASEURL";
}.q{
$(document).ready(function(){
  $('#baseurl').bind("keypress change",function() {
    var base = $('#baseurl').val();
    $('#cgibinurl').val( base + "cgi-bin/"); 
  });
  $('#docroot').bind("keypress change",function() {
    var base = $('#docroot').val();
    $('#cgibin').val( base + "cgi-bin/"); 
  });
});
</script>
    };
    print q{<form action="mt-install.cgi">};
    print q{  <h2>Does this look right to you?</h2>};
    print q{  <ul class="paths">};

    print q{    <li class="pkg"><label>Homepage URL: <input type="text" id="baseurl" name="baseurl" value="}."http" . ($Q->https() ? 's' : '') . "://" .$Q->server_name().q{" size="40" /></label></li>};
    print q{    <li class="pkg"><label>Path to Document Root: <input type="text" id="docroot" name="docroot" value="}.$ENV{DOCUMENT_ROOT}.q{" size="40" /></label></li>};

    print q{    <li class="pkg"><label>URL to cgi-bin: <input type="text" id="cgibinurl" name="cgibinurl" value="http}.($Q->https() ? 's' : '') . "://" .$Q->server_name().q{/cgi-bin/" size="40" /></label></li>};
    print q{    <li class="pkg"><label>Path to cgi-bin: <input type="text" id="cgibin" name="cgibin" value="}.getcwd.q{" size="40" /></label></li>};

    print q{  </ul>};
    print q{  <p><input type="submit" name="submit" value="Begin" /></p>};
    print q{</form>};
}

sub check_for_available_install_options {
    my $can_one = 
	is_cgibin_writable() && 
	cgibin_can_serve_static_files();
    my $can_two = 
	is_docroot_writable() &&
	docroot_can_serve_cgi() &&
	check_htaccess_and_cgi();
    my $can_three = 
	is_cgibin_writable() && 
	is_docroot_writable();
    return ($can_one,$can_two,$can_three);
}

sub prompt_for_install_option() {
    my ($can_one,$can_two,$can_three) = check_for_available_install_options();
    print q{<form action="mt-install.cgi">};
    print q{  <input type="hidden" name="docroot" value="$DOCROOT" />};
    print q{  <input type="hidden" name="cgibin" value="$CGIBIN" />};
    print q{  <input type="hidden" name="mtstatic" value="$MTSTATIC" />};
    print q{  <ul class="install_opt">};
    print q{    <li class="pkg }.($can_one ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="1" /> Install all of Open Melody in cgi-bin</label></li>};
    print q{    <li class="pkg }.($can_two ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="2" /> Install all of Open Melody in document root</label></li>};
    print q{    <li class="pkg }.($can_three ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="3" /> Install app files in cgi-bin, and static files in document root</label></li>};
    print q{  </ul>};
    print q{  <p><input type="submit" name="submit" value="Next" /></p>};
    print q{</form>};
}

sub debug {
    my ($str) = @_;
    print "<p>$str</p>\n" if DEBUG;
}

sub write_test_file {
    my $dir = getcwd;
    my $file = File::Spec->catfile($dir , TEST_FILE);
    my $fail = 0;
    open FILE,">$file" or $fail = 1;
    if ($fail) {
#    debug("Writing test file '$file': failed, $!");
	return 0;
    }
    print FILE "ok";
    close FILE;
#    debug("Writing test file '$file': success!");
    return 1;
}

sub get_current_url {
    my $Q = new CGI;
    my $url = "http" . ($Q->https() ? 's' : '') . "://" . $Q->server_name() . $Q->script_name();
#    debug("Current URL is: $url");
    return $url;
}

sub _getfile {
    my ($url) = @_;
#    debug("Fetching $url");
    my $ua = new LWP::UserAgent;
    $ua->agent("Movable Type Installer/".VERSION); 
    my $req = new HTTP::Request GET => $url;
    return $ua->request($req);
}

sub cgibin_can_serve_static_files {
    write_test_file();
    my $content;
    my $url = get_current_url();
    $url =~ s/mt-install.cgi//;
    $url .= TEST_FILE;
    my $res = _getfile($url);
    if ($res->is_success) {
	if ($res->content ne 'ok') {
#	    debug("Contents of test file are incorrect: ".$res->content);
	    return 0;
	} 
    } else {
#	debug("Could not get test file.");
	return 0;
    }
#    debug("cgi-bin directory can serve static files.");
    return 1;
}

sub main {
    if (!$DOCROOT || !$CGIBIN) {
	prompt_for_file_paths();
    } elsif (!$FOLDER) {
	prompt_for_mthome();
    } elsif (!$TYPE) {
	prompt_for_install_option();
    } else {
	prerequisites_check();
	download_openmelody();
    }
}

sub print_header {
    print header;
    my $html = <<EOH;
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" id="sixapart-standard">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>Open Melody Installer</title>
    <script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.3/jquery.min.js"></script>
    <style>
body {
  font-family: Georgia;
  }
ul.paths li label {
  display: block;
  width: 125px;
  float: left;
  font-weight: bold;
  }
ul.paths li input {
  float: left;
  }
li.impossible { 
  color: red; 
  }
ul {
  margin-left: 0;
  padding-left: 0;
  }
#container form li {
  list-style: none;
  margin-left: 0;
  margin-bottom: 10px;
  padding-left: 0;
  }
input#mthome,
input#mtstatic {
  border: 0;
  background: transparent;
  font-family:courier;
}


.pkg:after {
      content: " ";
      display: block;
      visibility: hidden;
      clear: both;
      height: 0.1px;
      font-size: 0.1em;
      line-height: 0;
}
.msg-success{background-image:url('http://localhost/~breese/mt/mt-static/images/icon_success.png');}
.msg-error{background-image:url('http://localhost/~breese/mt/mt-static/images/icon_error.png');}
.msg-info{background-image:url('http://localhost/~breese/mt/mt-static/images/icon_info.gif');}
.msg-alert{background-image:url('http://localhost/~breese/mt/mt-static/images/icon_alert.png');}
.msg-publishing{background-image:url('http://localhost/~breese/mt/mt-static/images/ani-rebuild.gif');}
.msg a.close-me{background:transparent url('http://localhost/~breese/mt/mt-static/images/icon_close.png') no-repeat scroll 3px 4px;}

#container-inner{background:url('http://localhost/~breese/mt/mt-static/images/chromeless/chromeless_bg_b.png') repeat-x bottom center;}
#nav .step{background:url('http://localhost/~breese/mt/mt-static/images/chromeless/nav_off.png');}
#nav .step_active{background:url('http://localhost/~breese/mt/mt-static/images/chromeless/nav_on.png');}


/* Begin Simple CSS */
/* Movable Type (r) (C) 2001-2009 Six Apart, Ltd. All Rights Reserved
 * This file is combined from multiple sources.  Consult the source files for their
 * respective licenses and copyrights.
 */
:link,:visited{text-decoration:none;}html,body,div,
ul,ol,li,dl,dt,dd,
form,fieldset,input,textarea,
h1,h2,h3,h4,h5,h6,pre,code,p,blockquote,hr,th,td{margin:0;padding:0;}
h1,h2,h3,h4,h5,h6{font-size:100%;font-weight:normal;}table{border-spacing:0;}fieldset,img,abbr,acronym{border:0;}address,caption,cite,code,dfn,em,strong,b,u,s,i,th,var{font-style:normal;font-weight:normal;}ol,ul{list-style:none;}caption,th{text-align:left;}q:before,q:after{content:'';}a{text-decoration:underline;outline:none;}hr{border:0;height:1px;background-color:#000;color:#000;}a img,:link img,:visited img{border:none;}address{font-style:normal;}.msg{margin:0 0 10px 0;padding:16px 10px 16px 46px;background-repeat:no-repeat;background-position:12px center;}.msg-success{background-color:#CFC;}.msg-error{background-color:#FF9;}.msg-info{background-color:#fff;}.msg-alert{background-color:#FF9;}.msg-publishing{background-color:#fff;}.msg a.close-me{display:block;float:right;height:18px;min-width:0;padding:2px;width:22px;margin:0;}.msg a.close-me span{display:none;}#system-allow-pings a.close-me,
#system-allow-comments a.close-me,
.msg-error a.close-me,
.rebuilding-screen .msg a.close-me,
.restore-publishing-config .msg a.close-me,
.insert-asset-dialog .msg a.close-me,
.edit-template .msg-info a.close-me,
.rebuilding-screen .msg-info a.close-me,
.pinging-screen .msg-info a.close-me,
.list-notification .msg-info a.close-me,
    .zero-state a.close-me{display:none;}.debug-panel{width:100%;border-top:1px dotted #f55;margin-top:5px;background-color:#daa;text-align:left;}.debug-panel h3{padding:5px;font-size:12px;margin:0;background-color:#f55;color:#fff;}.debug-panel-inner li{white-space:pre;}.debug-panel-inner li:hover{background-color:#eaa;}.debug-panel-inner{padding:5px;font-family:'Andale Mono', monospace;font-size:10px;max-height:200px;overflow:auto;}body{font-family:"Helvetica Neue", Helvetica, Arial, sans-serif;font-size:12px;background-color:#fff;}
h1, h2, p, ul{margin-bottom:12px;}
h2{font-weight:bold;font-size:14px;}
strong{font-weight:bold;}em{font-style:italic;}a:link,
a:visited{color:#33789c;}a:hover,
a:active{color:#a2ad00;}#container{margin:50px auto 0;text-align:left;width:360px;}.ready{font-weight:bold;color:#93b06b;}.note{clear:both;padding:10px 0 10px 0;}#page-title{font-size:24px;font-weight:normal;margin-top:10px;}p.intro{font-size:14px;font-weight:normal;}.hint{line-height:1.1;font-size:11px;padding-top:2px;}#db_hint{margin-top:-10px;margin-bottom:10px;}#db_hint p{margin-bottom:3px;}#error_more{margin:10px 0 15px;font-weight:normal;overflow:auto;padding:5px 0 10px 0;}#continue{margin-bottom:20px;}.module-name{font-weight:bold;}.module-name a{color:black;text-decoration:none;}.module-name a:hover{text-decoration:underline;}#brand{position:relative;margin:30px 0 0 20px;height:34px;width:192px;font-size:32px;font-family:Helvetica;font-weight: bold;}#container-inner{border:1px solid #cfdde5;}#content #content-inner{margin:0 18px;}#nav{float:right;margin-right:20px;}#nav .step{float:left;height:15px;width:14px;}#nav .step_active{float:left;height:15px;width:14px;}.edit-entry .actions-bar-top,.edit-entry .actions-bar-bottom{display:none;}#container.show-actions-bar-top .actions-bar-top{display:block;}#container.show-actions-bar-bottom .actions-bar-bottom{display:block;}ul li{list-style-type:disc;margin-left:15px;}fieldset{margin:0;}.field{border:0;mat-weight:bold;margin-boctions-bar .plugin-actions button{width:auto;overflow:visible;}.buttons a:hover,
.buttons a:active,
.buttons button:hover,
.listing .actions-bar .actions a:hover,
.listing .actions-bar .actions a:active,
.listing .actions-bar .actions button:hover,
.actions-bar .plugin-actions a:hover,
.actions-bar .plugin-actions a:active,
.actions-bar .plugin-actions button:hover{color:#33789c !important;background-position:50% 30%;}.system .buttons a:hover,
.system .buttons a:active,
.system .buttons button:hover,
.system .listing .actions-bar .actions a:hover,
.system .listing .actions-bar .actions a:active,
.system .listing .actions-bar .actions button:hover,
.system .actions-bar .plugin-actions a:hover,
.system .actions-bar .plugin-actions a:active,
.system .actions-bar .plugin-actions button:hover{color:#7f8833 !important;}
.dialog .actions-bar{margin-bottom:10px;}.dialog .actions-bar-login .actions a,
.dialog .actions-bar-login .actions button,
.dialog .actions-bar-login .actions select{float:left;margin:0 5px 0 0;}.upgrade .upgrade-process{overflow:auto;margin:10px 0;border:1px solid #ccc;padding:10px;background-color:#fafafa;height:200px;}.mt-config-file-path{overflow:auto;overflow-x:auto;overflow-y:hidden;height:2.75em;font-weight:bold;}ul#profile-data li{margin-left:0;padding-left:0;list-style:none;}#profile_userpic-field .field-content label{display:block;margin-top:5px;}.mt-profile-edit form{margin-bottom:.75em;}.custom-field-radio-list{margin-bottom:.25em;}.custom-field-radio-list li{list-style:none;margin-left:0;}.pkg:after{content:" ";display:block;visibility:hidden;clear:both;height:0.1px;font-size:0.1em;line-height:0;}.pkg{display:inline-block;}/*\*/* html .pkg{height:1%;}.pkg[class]{height:auto;}.pkg{display:block;}/**/.hidden{display:none !important;}.visible{display:block;}.invisible{display:block !important;visibility:hidden !important;position:absolute !important;left:0 !important;top:0 !important;width:0 !important;height:0 !important;font-size:0.1px !important;line-height:0 !important;}.overflow-auto{overflow:auto;}.overflow-hidden{overflow:hidden;}.right{float:right;}.left{float:left;display:inline;}.center{margin-left:auto;margin-right:auto;}.inline{display:inline;}.nowrap{white-space:nowrap;}
/* End Simple CSS */

.pkg { display: inline-block; }
/* no ie mac \*/
* html .pkg {
      height: 1%;
}
.pkg { display: block; }
/* */
    </style>
</head>
<body id="" class="chromeless dialog">
<div id="container">
<div id="container-inner">
    <div id="ctl"></div>
    <div id="ctr"></div>
    <div id="header" class="pkg">
        <div id="brand"><h1>Open Melody</h1></div>
        <div id="nav">
        </div>
    </div>
    <div id="content">
        <div id="content-inner" class="inner pkg">
            <div id="main-content"><div id="main-content-inner" class="inner pkg">
                <h2 id="page-title">Installation</h2>
                <div class="upgrade">
EOH
    print $html;
}

sub print_footer {
    print qq{
                </div>
            </div>
        </div>
    </div>
    <div id="cbl"></div>
    <div id="cbr"></div>
    <div id="footer">

        <div class="inner">
            
        </div>
    </div>
</div><!-- container-inner-->
</div><!--container--></body>
</html>
    };
}

BEGIN {

package File::Download;

# use 'our' on v5.6.0
use vars qw($VERSION @EXPORT_OK %EXPORT_TAGS $DEBUG);

$DEBUG = 0;
$VERSION = '0.1';

use base qw(Class::Accessor);
File::Download->mk_accessors(qw(mode overwrite outfile flength size status user_agent saved));

# We are exporting functions
use base qw/Exporter/;

# Export list - to allow fine tuning of export table
@EXPORT_OK = qw( download );

use strict;
use LWP::UserAgent ();
use LWP::MediaTypes qw(guess_media_type media_suffix);
use URI ();
use HTTP::Date ();

# options:
# - url
# - filename
# - username
# - password
# - overwrite
# - mode ::= a|b

sub DESTROY { }

$SIG{INT} = sub { die "Interrupted\n"; };

$| = 1;  # autoflush

sub download {
    my $self = shift;
    my ($url) = @_;
    my $file;
    $self->{user_agent} = LWP::UserAgent->new(
	agent => "File::Download/$VERSION ",
	keep_alive => 1,
	env_proxy => 1,
	) if !$self->{user_agent};
    my $ua = $self->{user_agent};
    my $res = $ua->request(HTTP::Request->new(GET => $url),
      sub {
	  $self->{status} = "Beginning download\n";
	  unless(defined $file) {
	      my ($chunk,$res,$protocol) = @_;

	      my $directory;
	      if (defined $self->{outfile} && -d $self->{outfile}) {
		  ($directory, $self->{outfile}) = ($self->{outfile}, undef);
	      }

	      unless (defined $self->{outfile}) {
		  # find a suitable name to use
		  $file = $res->filename;
		  # if this fails we try to make something from the URL
		  unless ($file) {
		      my $req = $res->request;  # not always there
		      my $rurl = $req ? $req->url : $url;
		      
		      $file = ($rurl->path_segments)[-1];
		      if (!defined($file) || !length($file)) {
			  $file = "index";
			  my $suffix = media_suffix($res->content_type);
			  $file .= ".$suffix" if $suffix;
		      }
		      elsif ($rurl->scheme eq 'ftp' ||
			     $file =~ /\.t[bg]z$/   ||
			     $file =~ /\.tar(\.(Z|gz|bz2?))?$/
			  ) {
			  # leave the filename as it was
		      }
		      else {
			  my $ct = guess_media_type($file);
			  unless ($ct eq $res->content_type) {
			      # need a better suffix for this type
			      my $suffix = media_suffix($res->content_type);
			      $file .= ".$suffix" if $suffix;
			  }
		      }
		  }

		  # validate that we don't have a harmful filename now.  The server
		  # might try to trick us into doing something bad.
		  if ($file && !length($file) ||
		      $file =~ s/([^a-zA-Z0-9_\.\-\+\~])/sprintf "\\x%02x", ord($1)/ge)
		  {
		      die "Will not save <$url> as \"$file\".\nPlease override file name on the command line.\n";
		  }
		  
		  if (defined $directory) {
		      require File::Spec;
		      $file = File::Spec->catfile($directory, $file);
		  }
		  # Check if the file is already present
		  if (-l $file) {
		      die "Will not save <$url> to link \"$file\".\nPlease override file name on the command line.\n";
		  }
		  elsif (-f _) {
		      die "Will not save <$url> as \"$file\" without verification.\nEither run from terminal or override file name on the command line.\n"
			  unless -t;
		      return 1 if (!$self->{overwrite});
		  }
		  elsif (-e _) {
		      die "Will not save <$url> as \"$file\".  Path exists.\n";
		  }
		  else {
		      $self->{status} = "Saving to '$file'...\n";
		  }
	      }
	      else {
		  $file = $self->{file};
	      }
	      open(FILE, ">$file") || die "Can't open $file: $!\n";
	      binmode FILE unless $self->{mode} eq 'a';
	      $self->{length} = $res->content_length;
	      $self->{flength} = fbytes($self->{length}) if defined $self->{length};
	      $self->{start_t} = time;
	      $self->{last_dur} = 0;
	  }
	  
	  print FILE $_[0] or die "Can't write to $file: $!\n";
	  $self->{size} += length($_[0]);
	  
	  if (defined $self->{length}) {
	      my $dur  = time - $self->{start_t};
	      if ($dur != $self->{last_dur}) {  # don't update too often
		  $self->{last_dur} = $dur;
		  my $perc = $self->{size} / $self->{length};
		  my $speed;
		  $speed = fbytes($self->{size}/$dur) . "/sec" if $dur > 3;
		  my $secs_left = fduration($dur/$perc - $dur);
		  $perc = int($perc*100);
		  $self->{status} = "$perc% of ".$self->{flength};
		  $self->{status} .= " (at $speed, $secs_left remaining)" if $speed;
	      }
	  }
	  else {
	      $self->{status} = "Finished. " . fbytes($self->{size}) . " received";
	  }
       });
    if (fileno(FILE)) {
	close(FILE) || die "Can't write to $file: $!\n";
	$self->{saved} = $file;

	$self->{status} = "";  # clear text
	my $dur = time - $self->{start_t};
	if ($dur) {
	    my $speed = fbytes($self->{size}/$dur) . "/sec";
	}
	
	if (my $mtime = $res->last_modified) {
	    utime time, $mtime, $file;
	}
	
	if ($res->header("X-Died") || !$res->is_success) {
	    if (my $died = $res->header("X-Died")) {
		$self->{status} = $died;
	    }
	    if (-t) {
		if ($self->{autodelete}) {
		    unlink($file);
		}
		elsif ($self->{length} > $self->{size}) {
		    $self->{status} = "Aborted. Truncated file kept: " . fbytes($self->{length} - $self->{size}) . " missing";
		}
		return 1;
	    }
	    else {
		$self->{status} = "Transfer aborted, $file kept";
	    }
	}
	return 0;
    }
    return 1;
}

sub fbytes
{
    my $n = int(shift);
    if ($n >= 1024 * 1024) {
	return sprintf "%.3g MB", $n / (1024.0 * 1024);
    }
    elsif ($n >= 1024) {
	return sprintf "%.3g KB", $n / 1024.0;
    }
    else {
	return "$n bytes";
    }
}

sub fduration
{
    use integer;
    my $secs = int(shift);
    my $hours = $secs / (60*60);
    $secs -= $hours * 60*60;
    my $mins = $secs / 60;
    $secs %= 60;
    if ($hours) {
	return "$hours hours $mins minutes";
    }
    elsif ($mins >= 2) {
	return "$mins minutes";
    }
    else {
	$secs += $mins * 60;
	return "$secs seconds";
    }
}

}
