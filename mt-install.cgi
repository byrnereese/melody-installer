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
use CGI;
use LWP::UserAgent;
use File::Spec;
use File::Find;
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

my $cgi;
BEGIN { $cgi = new CGI; }
my $JSON      = $cgi->param('json');
my $TYPE      = $cgi->param('type');
my $FOLDER    = $cgi->param('folder');
my $UPGRADE   = $cgi->param('upgrade');
my $OK        = $cgi->param('proceed');

my $DOCROOT   = $cgi->param('docroot');
my $BASEURL   = $cgi->param('baseurl');
my $CGIBIN    = $cgi->param('cgibin');
my $CGIBINURL = $cgi->param('cgibinurl');

my $DBNAME    = $cgi->param('dbname');
my $DBUSER    = $cgi->param('dbuser');
my $DBPASS    = $cgi->param('dbpass');
my $DBHOST    = $cgi->param('dbhost');

my $PREREQS = {
    'CGI' => {
	version => 0,
	required => 1,
	description => 'CGI is required for all Movable Type application functionality.',
    },
    'Image::Size' => {
	version => 0,
	required => 1,
	description => 'Image::Size is required for file uploads (to determine the size of uploaded images in many different formats).',
    },
    'File::Spec' => {
	version => 0.8,
	required => 1,
	description => 'File::Spec is required for path manipulation across operating systems.',
    },
    'CGI::Cookie' => {
	version => 0,
	required => 1,
	description => 'CGI::Cookie is required for cookie authentication.',
    },
    'DBI' => {
	version => 1.21, 
	required => 1,
	description => 'DBI is required to store data in database.',
    },
    'DBD::mysql' => {
	version => 0,
	required => 1,
	description => 'DBI and DBD::mysql are required if you want to use the MySQL database backend.',
    },
    'HTML::Entities' => {
	version => 0,
	required => 0,
	description => 'HTML::Entities is needed to encode some characters, but this feature can be turned off using the NoHTMLEntities option in the configuration file.',
	short => 'HTML Encoding',
    },
    'LWP::UserAgent' => {
	version => 0,
	required => 0,
	description => 'LWP::UserAgent is optional; It is needed if you wish to use the TrackBack system, the weblogs.com ping, or the MT Recently Updated ping.',
	short => 'TrackBack',
    },
    'HTML::Parser' => {
	version => 0, 
	required => 0,
	description => 'HTML::Parser is optional; It is needed if you wish to use the TrackBack system, the weblogs.com ping, or the MT Recently Updated ping.',
	short => 'TrackBack',
    },
    'SOAP::Lite' => {
	version => 0.50,
	required => 0,
	description => 'SOAP::Lite is optional; It is needed if you wish to use the MT XML-RPC server implementation.',
	short => 'XML-RPC',
    },
    'File::Temp' => {
	version => 0,
	required => 0,
	description => 'File::Temp is optional; It is needed if you would like to be able to overwrite existing files when you upload.',
	short => "Upload file overwrite",
    },
    'Scalar::Util' => {
	version => 0,
	required => 1, 
	description => 'Scalar::Util is optional; It is needed if you want to use the Publish Queue feature.',
	short => 'Publish Queue',
    },
    'List::Util' => {
	version => 0,
	required => 1,
	description => 'List::Util is optional; It is needed if you want to use the Publish Queue feature.',
	short => 'Publish Queue',
    },
    'Image::Magick' => {
	version => 0,
	required => 0,
	description => 'Image::Magick is optional; It is needed if you would like to be able to create thumbnails of uploaded images.',
	short => 'Image manipulation, userpics and thumbnails',
    },
    'Storable' => {
	version => 0,
	required => 0,
	description => 'Storable is optional; it is required by certain MT plugins available from third parties.',
	short => "Some plugins",
    },
    'Crypt::DSA' => {
	version => 0, 
	required => 0,
	description => 'Crypt::DSA is optional; if it is installed, comment registration sign-ins will be accelerated.',
	short => 'Feature: High performant comment authentication',
    },
#    'MIME::Base64', 0, 0, 'MIME::Base64 is required in order to enable comment registration.','Comment Registration',
#    'XML::Atom', 0, 0, 'XML::Atom is required in order to use the Atom API.','Atom Publishing Protocol',
#    'Cache::Memcached', 0, 0, 'Cache::Memcached and memcached server/daemon is required in order to use memcached as caching mechanism used by Movable Type.','Memcache',
#    'Archive::Tar', 0, 0, 'Archive::Tar is required in order to archive files in backup/restore operation.','Backup/Restore',
#    'IO::Compress::Gzip', 0, 0, 'IO::Compress::Gzip is required in order to compress files in backup/restore operation.','Backup/Restore',
#    'IO::Uncompress::Gunzip', 0, 0, 'IO::Uncompress::Gunzip is required in order to decompress files in backup/restore operation.','Backup/Restore',
#    'Archive::Zip', 0, 0, 'Archive::Zip is required in order to archive files in backup/restore operation.','Backup/Restore',
#    'XML::SAX', 0, 0, 'XML::SAX and/or its dependencies is required in order to restore.','Backup/Restore',
#    'Digest::SHA1', 0, 0, 'Digest::SHA1 and its dependencies are required in order to allow commenters to be authenticated by OpenID providers including Vox and LiveJournal.','OpenID',
#    'Mail::Sendmail', 0, 0, 'Mail::Sendmail is required for sending mail via SMTP Server.','SMTP',
#    'Safe', 0, 0, 'This module is used in test attribute of MTIf conditional tag.','mt:if',
#    'Digest::MD5', 0, 0, 'This module is used by the Markdown text filter.','Markdown',
#    'Text::Balanced', 0, 0, 'This module is required in mt-search.cgi if you are running Movable Type on Perl older than Perl 5.8.','Search',
    'FCGI' => {
	version => 0, 
	required => 0,
	description => 'FCGI is needed in order to run under FastCGI.',
	short => 'FastCGI',
    },
};


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

sub check_for_prereqs {
    my $results;
    for my $mod (keys %$PREREQS) {
	if ('CODE' eq ref($PREREQS->{$mod}->{description})) {
#	    $desc = $PREREQS->{$mod}->{description}->();
	}
	my $ver = $PREREQS->{$mod}->{version};
	eval("use $mod" . ($ver ? " $ver;" : ";"));
	if ($@) {
	    $results->{$mod}->{ok} = 0;
	} else {
	    $results->{$mod}->{ok} = 1;
	}
	$results->{$mod}->{required} = $PREREQS->{$mod}->{required};
    }
    return $results;
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

sub get_install_destination {
    my ($app,$static);
    if ($TYPE == 1) {
	# all in cgi-bin
	$app    = File::Spec->catdir($CGIBIN, $FOLDER);
	$static = File::Spec->catdir($CGIBIN, $FOLDER, 'mt-static');
    } elsif ($TYPE == 2) {
	# all in docroot
	$app    = File::Spec->catdir($DOCROOT, $FOLDER);
	$static = File::Spec->catdir($DOCROOT, $FOLDER, 'mt-static');
    } elsif ($TYPE == 3) {
	$app    = File::Spec->catdir($CGIBIN, $FOLDER);
	$static = File::Spec->catdir($DOCROOT, 'mt-static');
    }
    return ($app, $static);
}

sub install {
    eval 'use Archive::Extract';
#    $Archive::Extract::DEBUG = 1;
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
    my ($mtdir) = ($archive->extract_path =~ /([^\/]*)$/);
    debug("root = $mtdir");
    my $files = $archive->files;
    foreach my $file (@$files) {
	my $dest = $file;
	$dest =~ s/^$mtdir\/?//;
	my $orig = File::Spec->catfile($archive->extract_path, $dest);
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
	    chmod 0755, $dest if ($dest =~ /^mt-static\/support/);
	} elsif (-f $orig) {
	    debug("Intalling $orig into $dest");
	    copy($orig,$dest);
	    chmod 0755, $dest if ($orig =~ /\.cgi$/);
	} else {
	    debug("Something weird happened when copying $orig. Its not a file for directory.");
	}
    }
    # Finished. Now, let's install the config.
    my ($dest,$cgi,$static);
    if ($TYPE == 1) {
	# all in cgi-bin
	$dest = File::Spec->catfile($CGIBIN, $FOLDER, 'mt-config.cgi');
	$cgi = $CGIBINURL;
	$static = File::Spec->catdir($CGIBINURL, $FOLDER, 'mt-static');
    } elsif ($TYPE == 2) {
	# all in docroot
	$dest = File::Spec->catfile($DOCROOT, $FOLDER, 'mt-config.cgi');
	$cgi = $BASEURL;
	$static = File::Spec->catdir($BASEURL, $FOLDER, 'mt-static');
    } elsif ($TYPE == 3) {
	# app in cgi-bin, static in docroot
	$dest = File::Spec->catfile($CGIBIN, $FOLDER, 'mt-config.cgi');
	$cgi = $CGIBINURL;
	$static = File::Spec->catdir($BASEURL, 'mt-static');
    }
    write_config($dest,$cgi,$static);
}

sub make_tmpdir {
    my $dir = tempdir( );
    chmod 0775, $dir;
    return $dir;
}

sub check_htaccess_and_cgi {
    my $tmpdir = 'tmp_' . int(rand(1000000));
    my $dir = File::Spec->catdir($DOCROOT , $tmpdir);
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
    return check_install_options();
}

sub prompt_for_mthome_html {
    my ($options)   = @_;
    my $can_one     = $options->{types}->{1}->{ok};
    my $can_two     = $options->{types}->{2}->{ok};
    my $can_three   = $options->{types}->{3}->{ok};
    my $can_install = $can_one || $can_two || $can_three;
    my $html;
    $html .= q{
<script type="text/javascript">
function change_urls(e) {
  var baseurl;
  if ( $(e).val() == 1 ) {
     $('#folder-static').fadeOut('fast');
     $('#url-static').fadeOut('fast');
     baseurl = cgibin_url;
  } else if ( $(e).val() == 2 ) {
     $('#folder-static').fadeOut('fast');
     $('#url-static').fadeOut('fast');
     baseurl = docroot_url;
  } else if ( $(e).val() == 3 ) {
     $('#folder-static').fadeIn('fast');
     $('#url-static').fadeIn('fast');
     baseurl = cgibin_url;
  }
  var url = baseurl + $('#folder-mthome input').val() + '/mt.cgi';
  $('#mthome').val( url );
}
$(document).ready(function(){
  $('#tryagain').click(function(){
    if (open_drawer_is != 0) { close_drawer(); }
    begin();
  });
  $('.folder').bind('change keyup', function() {
    var app = $('#folder-mthome input').val();
    var static = $('#folder-static input').val();
    $('#url-mthome input').val( baseurl + app + "/mt.cgi" );
    $('#url-static input').val( baseurl + static + '/' ); 
  });
  var selected = 0;
  $('.install-type').each(function(i,e){ 
     if ($("#" + this.id).hasClass('impossible')) {
       $('#' + this.id + ' input').attr('disabled', true);
     } else {
       if (!selected) {
         $('#' + this.id + ' input').attr('checked', true).trigger('click');
         selected = this.id;
       }
     }
  });
});
</script>
  <h2>Choose an install option</h2>
  <ul class="install_opt">
};
    $html .= q{    <li id="type1" class="install-type pkg }.($can_one ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="1" onclick="change_urls(this);" /> Install all of Open Melody in cgi-bin</label> }.(!$can_one ? '<a href="#" id="fixme-1" class="fixme install-1">Fix me</a>' : '').q{</li>};
    $html .= q{    <li id="type2" class="install-type pkg }.($can_two ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="2" onclick="change_urls(this);" /> Install all of Open Melody in document root</label> }.(!$can_two ? '<a href="#" id="fixme-2" class="fixme install-2">Fix me</a>' : '').q{</li>};
    $html .= q{    <li id="type3" class="install-type pkg }.($can_three ? 'possible' : 'impossible').q{"><label><input type="radio" name="type" value="3" onclick="change_urls(this);" /> Install app files in cgi-bin, and static files in document root</label> }.(!$can_three ? '<a href="#" id="fixme-3" class="fixme install-3">Fix me</a>' : '').q{</li>};
    $html .= q{  </ul>};

    if ($can_install) {
	$html .= q{  <h2>Where do you want to install this puppy?</h2>};
	$html .= q{  <ul class="folders">};
	$html .= q{    <li id="folder-mthome" class="pkg folder"><label>Folder to install application: <input type="text" name="folder" value="mt" size="40" /></label></li>};
	$html .= q{    <li id="folder-static" class="pkg folder" style="display:none;"><label>Folder to install css and javascript files: <input type="text" name="folder-static" value="mt-static" size="40" /></label></li>};
	$html .= q{  </ul>};
	
	$html .= q{  <ul class="urls">};
	$html .= qq{    <li id="url-mthome" class="pkg wrap url"><label for="mthome">URL to Open Melody Admin:</label><input type="text" id="mthome" name="mthome" size="40" value="" /></li>};
	
	$html .= qq{    <li id="url-static" class="pkg wrap url" style="display: none"><label for="mtstatic">URL to Static Content:</label><input type="text" id="mtstatic" name="mtstatic" size="40" value="" /></li>};
	$html .= q{  </ul>};
	
	$html .= q{  <p><button id="next-checkprereq">Next</button></p>};
    } else {
	$html .= q{<p>It looks like your system is not ready yet. To install Open Melody try to fix one of the options above. Click "Fix me" for help.</p>};
	$html .= q{<button id="tryagain">Try Again</button>};
    }
    return $html;
}

sub prompt_for_db_info_html {
    my $html = '';
    $html .= q{  <h2>Database time</h2>};
    $html .= q{  <ul class="db-info">};
    $html .= q{    <li class="pkg"><label>Database Host: <input type="text" id="dbhost" name="dbhost" value="localhost" size="40" /></label></li>};
    $html .= q{    <li class="pkg"><label>Database User: <input type="text" id="dbuser" name="dbuser" value="" size="40" /></label></li>};
    $html .= q{    <li class="pkg"><label>Database Password: <input type="password" id="dbpass" name="dbpass" value="" size="40" /></label></li>};
    $html .= q{    <li class="pkg"><label>Database Name: <input type="text" id="dbname" name="dbname" value="movabletype" size="40" /></label></li>};
    $html .= q{  </ul>};
    $html .= q{  <p><input type="submit" name="submit" value="Next" /></p>};
    return $html;
}

sub _cgi_server_path {
    my $path = MT->instance->server_path() || "";
    $path =~ s!/*$!!;
    return $path;
}

sub _static_file_path {
    my $cfg = MT::ConfigMgr->instance;
    my $path = $cfg->StaticFilePath;
    if (!$path) {
        $path = MT->instance->{mt_dir};
        $path .= '/' unless $path =~ m!/$!;
        $path .= 'mt-static/';
    }
    $path .= '/' unless $path =~ m!/$!;
    return $path;
}

sub find_installs {
    my $installs;
    find(sub {
	if ($File::Find::name =~ /mt-config.cgi$/) {
	    $installs->{$File::Find::dir}->{ok} = 1;
	    $installs->{$File::Find::dir}->{app} = $File::Find::dir;
	    $installs->{$File::Find::dir}->{static} = eval q{
		BEGIN { 
                  unshift @INC, File::Spec->catdir($File::Find::dir, "lib");
                  unshift @INC, File::Spec->catdir($File::Find::dir, "extlib"); 
                  #print join('<br>',@INC);
                }
                require MT;
                $ENV{MT_HOME} = $File::Find::dir;
                my $mt = MT->new;
                $mt->init_config( {
                    Config => $File::Find::name, 
                    Directory => $File::Find::dir,
                });
                my $path = $mt->static_file_path;
		#debug("cgi path: $File::Find::dir<br>static path: $path");
                shift @INC; shift @INC;
                delete $mt->{__static_file_path};
                return $path;
	    };
	}
	 }, ( $CGIBIN, $DOCROOT) );
    foreach my $dir ( sort keys %$installs ) {
	find(sub {
	    $installs->{$dir}->{ok} = 0 if (!-w $File::Find::name);
	     }, ($dir) );
    }
    return $installs;
}

sub prompt_for_upgrade_html {
    my ($installs) = @_;
    my @dirs = sort keys %$installs;
    my $html;
    $html .= q{
<script type="text/javascript">
$(document).ready(function(){
  static_path = '';
  $('#begin').click(function(){
    alert( "static: " + static_path );
    var result = $("input[name='upgrade']:checked").val();
    if (result == "no") {
      dest_app = 'foobar!';
    } else {
      dest_app = result;
    }
    begin();    
  });
});
</script>
    };
    $html .= q{  <h2>What do you want to do?</h2>};
    $html .= q{  <p>I have found a copy of Open Melody already installed on your system. Do you want to upgrade an existing install, or install a brand new copy?</p>};
    $html .= q{  <ul class="upgrade_opt">};
    $html .= q{    <li class="pkg"><label><input type="radio" name="upgrade" value="no" onclick="static_path='';" checked /> Install a new instance of Open Melody</label></li>};
    foreach my $dir (@dirs) {
	$html .= qq{    <li class="pkg }.($installs->{$dir}->{ok} ? "possible" : "impossible").qq{"><label><input type="radio" name="upgrade" value="$dir" onclick="cgibin_path='$installs->{$dir}->{app}'; static_path='$installs->{$dir}->{static}';" /> $dir</label>};
	if (!$installs->{$dir}->{ok}) {
	    $html .= qq{ <a href="#" class="fixme upgrade-opt" title="$dir">Fix me</a>};
	}
	$html .= qq{</li>};
    }
    $html .= q{  </ul>};
    $html .= q{  <p><button id="begin">Next</button></p>};
    return $html;
}

sub prompt_for_upgrade {
    print qq{
<script type="text/javascript">
var cgibin = "$CGIBIN";
var docroot = "$DOCROOT";
}.q{
$(document).ready(function(){
  begin();
});
</script>
    };
}

sub write_config {
    my ($dest,$cgi,$static) = @_;
    open CONFIG,">$dest";
    print CONFIG <<EOC;
# Open Melody configuration file
# This file defines system-wide settings for Movable Type

# The CGIPath is the URL to your Movable Type directory
CGIPath $cgi
StaticWebPath $static

# Database
ObjectDriver DBI::mysql
Database $DBNAME
DBHost $DBHOST
DBUser $DBUSER
EOC
    print "DBPassword $DBPASS\n" if $DBPASS && $DBPASS ne '';
    close CONFIG;
}

sub prompt_for_file_paths {
    print q{
<script type="text/javascript">
$(document).ready(function(){
  $('#baseurl').bind("keyup change",function() {
    var base = $('#baseurl').val();
    var lastchar = base.substr(base.length-1,1);
    $('#cgibinurl').val( base + (lastchar == '/' ? '' : "/") + "cgi-bin/"); 
  });
  $('#docroot').bind("keyup change",function() {
    var base = $('#docroot').val();
    var lastchar = base.substr(base.length-1,1);
    $('#cgibin').val( base + (lastchar == '/' ? '' : "/") + "cgi-bin/"); 
  });
  $('#begin').click(function(){
    /* Initialize all of the paths */
    docroot_path = $('#docroot').val();
    docroot_url  = $('#baseurl').val();
    cgibin_path  = $('#cgibin').val();
    cgibin_url   = $('#cgibinurl').val();
    begin();    
  });
});
</script>
    };
#    print q{<form action="mt-install.cgi">};
    print q{  <h2>Does this look right to you?</h2>};
    print q{  <ul class="paths">};

    print q{    <li class="pkg"><label>Homepage URL: <input type="text" id="baseurl" name="baseurl" value="}."http" . ($cgi->https() ? 's' : '') . "://" .$cgi->server_name().q{" size="40" /></label></li>};
    print q{    <li class="pkg"><label>Path to Document Root: <input type="text" id="docroot" name="docroot" value="}.$ENV{DOCUMENT_ROOT}.q{" size="40" /></label></li>};

    print q{    <li class="pkg"><label>URL to cgi-bin: <input type="text" id="cgibinurl" name="cgibinurl" value="http}.($cgi->https() ? 's' : '') . "://" .$cgi->server_name().q{/cgi-bin/" size="40" /></label></li>};
    print q{    <li class="pkg"><label>Path to cgi-bin: <input type="text" id="cgibin" name="cgibin" value="}.getcwd.q{" size="40" /></label></li>};

    print q{  </ul>};
    print q{  <p><button id="begin">Begin</button></p>};
#    print q{</form>};
}

sub check_install_options {
    my $options = {
	cgibin => $CGIBIN,
	docroot => $DOCROOT,
    };
    # Type 1: All in cgi-bin
    $options->{types}->{1}->{writable}  = is_cgibin_writable();
    $options->{types}->{1}->{exists}    = (-e $CGIBIN);
    $options->{types}->{1}->{directory} = (-d $CGIBIN);
    $options->{types}->{1}->{static_ok} = cgibin_can_serve_static_files();
    $options->{types}->{1}->{ok} = 
	$options->{types}->{1}->{writable} && 
	$options->{types}->{1}->{directory} && 
	$options->{types}->{1}->{static_ok};

    # Type 2: All in docroot
    $options->{types}->{2}->{writable} = is_docroot_writable();
    $options->{types}->{2}->{cgi_ok} = docroot_can_serve_cgi();
    $options->{types}->{2}->{exists}    = (-e $DOCROOT);
    $options->{types}->{2}->{directory} = (-d $DOCROOT);
    $options->{types}->{2}->{htaccess_ok} = check_htaccess_and_cgi();
    $options->{types}->{2}->{ok} = 
	$options->{types}->{2}->{writable} && 
	$options->{types}->{2}->{cgi_ok} && 
	$options->{types}->{2}->{htaccess_ok};

    # Type 3: Hybrid
    $options->{types}->{3}->{cgi_writable} = is_cgibin_writable();
    $options->{types}->{3}->{docroot_writable} = is_docroot_writable();
    $options->{types}->{3}->{cgi_exists} = (-e $CGIBIN);
    $options->{types}->{3}->{docroot_exists} = (-e $DOCROOT);
    $options->{types}->{3}->{cgi_directory} = (-d $CGIBIN);
    $options->{types}->{3}->{docroot_directory} = (-d $DOCROOT);
    $options->{types}->{3}->{ok} = 
	$options->{types}->{3}->{cgi_writable} && 
	$options->{types}->{3}->{docroot_writable};

    return $options;
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
    my $url = "http" . ($cgi->https() ? 's' : '') . "://" .
	$cgi->server_name() . $cgi->script_name();
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

sub prereq_html {
    my ($results) = @_;
    my $html = '';
    $html = "";
    $html .= "<ul>";
    my $can_continue = 1;
    foreach my $mod (sort keys %$results) {
	if (!$results->{$mod}->{ok}) {
	    $html .= qq{<li><code>$mod</code> is not installed, disabling the following feature: } . $PREREQS->{$mod}->{short} . qq{ <a href="#" class="fixme" title="$mod">Fix me</a></li>};
	    if ($results->{$mod}->{required} == 1) { $can_continue = 0; }
        }
    }
    $html .= q{</ul>};
    $html .= q{<button id="tryagain-prereq">Refresh</button>};
    $html .= q{<button id="next-dbinfo"}.($can_continue ? '' : ' disabled="true"').q{>Continue</button>};
}

if ($JSON) {
    print $cgi->header("application/json");
    if ($JSON eq 'find_installs') {
	my $installs = find_installs();
	my @dirs = sort keys %$installs;
	if ($#dirs == -1) {
	    # skip to the next step
	    $UPGRADE = "";
	    my $options = check_install_options();
	    my $html = prompt_for_mthome_html($options);
	    print JSON::objToJson({
		    'options' => $options,
		    'html' => $html,
		});
	} else {
	    print JSON::objToJson({
		    'dirs' => $installs,
		    'html' => prompt_for_upgrade_html($installs),
		});
	}
    } elsif ($JSON eq 'check_prereqs') {
	my $results = check_for_prereqs();
	my @mods = keys %$results;
	if ($#mods > -1) {
	    print JSON::objToJson({
		'results' => $results,
		'html' => prereq_html($results),
            });
	} else {
	    # TODO - prompt for database information
	}
    } elsif ($JSON eq 'db_info') {
	print JSON::objToJson({
	    'html' => prompt_for_db_info_html(),
	});
    } elsif ($JSON eq 'do_install') {
	my $files = install();
	print JSON::objToJson({
	    'files' => $files,
	    'html' => install_html($files),
	});
    }
} else {
    print_header();
    main();
    print_footer();
}

sub main {
    if (!$DOCROOT || !$CGIBIN) {
	prompt_for_file_paths();
    } elsif (!$UPGRADE) {
	prompt_for_upgrade();
    } elsif (!$FOLDER && $UPGRADE eq "no") {
	my ($options, $html) = prompt_for_mthome();
	print $html;
    } elsif (!$OK && $UPGRADE eq "no") {
	if (-e $FOLDER) {
	}
	prompt_for_prereqs();
    } elsif (!$DBNAME && $UPGRADE eq "no") {
	print prompt_for_db_info_html();
    } else {
	install();
    }
}

sub print_header {
    print $cgi->header;
    my $html = <<EOH;
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
    "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">

<html xmlns="http://www.w3.org/1999/xhtml" id="sixapart-standard">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=utf-8" />
    <title>Open Melody Installer</title>
    <script type="text/javascript" src="http://localhost/~breese/mt-byrne/mt-static/jquery/jquery.js"></script>
<!--
    <script type="text/javascript" src="http://ajax.googleapis.com/ajax/libs/jquery/1.3/jquery.min.js"></script>
-->
EOH
    $html .= q{
    <script type="text/javascript">
/* Globals */
var docroot_path;
var docroot_url;
var cgibin_path;
var cgibin_url;
var static_path;
var static_url;
var install_type;
var open_drawer_is = 0;
var is_animating = 0;
var pages = new Array();
function toggle_drawer(opener,new_html) {
  if (open_drawer_is == 0) { 
    $('#drawer-content').html(new_html);
    open_drawer(); 
    open_drawer_is = opener;
  } else if (open_drawer_is != 0) { 
    if (open_drawer_is == opener) {
      close_drawer(); 
      open_drawer_is = 0;
    } else {
      close_drawer(); 
      $('#drawer-content').html(new_html);
      open_drawer(); 
      open_drawer_is = opener;
    }
  }
}
function open_drawer() {
  var getWidth = $('#container-inner').width();
  is_animating = 1;
  $('#drawer').animate({ left: getWidth }, 500, function(){
    $('#drawer').css({ 'z-index':'100' });
    is_animating = 0;
  });
}
function close_drawer() {
  is_animating = 1;
  $('#drawer').css({ 'z-index':'-1' });
  $('#drawer').animate({ left: 15 }, 500, function(){
    is_animating = 0;
    drawer_is = 0;
  });
}
$(document).ready(function(){
    $('.close').click(function(){ close_drawer(); });
    $('#drawer').show();
    if (pages.length == 0) {
      $('#back').attr('disabled',true);
    }
    $('#back').click(function(){
      var html = pages.shift();
      $('#upgrade').html( html );
    });
});
function init_cpan_help(link,module) {
    var html = "<p>To enable this feature you will need to install the following Perl module. If you can, logon to your web server and run the following commands as root:</p><code><pre>";
    html += "cpan " + module + "\n";
    html += "</pre></code>";
    return html;
}
function init_setup_help(link,options) {
    var html = '';
    if (link.hasClass('install-1')) {
       html = "<p>We encountered the following problems when trying to install Open Melody into your <code>cgi-bin</code> directory:</p><ul>";
       var resolve = "";
       if (!options.types[1].exists) {
           html += "<li>The path you specified does not exist. (TODO - fix me)</li>";
           resolve += "<li>Connect to your web server and create the directory:<br><code>" + cgibin_path + "</code></li>";
       } else {
           if (!options.types[1].writable) {
               html += "<li>The cgi-bin directory you identified is not writable.</li>";
               resolve += '<li>Connect to your web server and change the permissions on the following directory <a href="#">learn how</a>:<br><code>' + cgibin_path + "</code></li>";
           }              
           if (!options.types[1].directory) {
               html += "<li>The path you specified for your cgi-bin is not a directory.</li>";
           }              
       }
       if (!options.types[1].static_ok) {
           html += "<li>The cgi-bin directory you identified is unable to serve static files like javascript, css or HTML.</li>";
       }              
       html += "</ul><h4>How to resolve the problem</h4><ul>";
       html += resolve;
       html += "</ul>";
    } else if (link.hasClass('install-2')) {
       html = "<p>We encountered the following problems when trying to install Open Melody into your document root:</p><ul>";
       var resolve = "";
       if (!options.types[2].directory) {
           html += "<li>The path you specified for your document root is not a directory.</li>";
           resolve += "<li>Connect to your web server and create the directory:<br><code>" + data.options.docroot + "</code></li>";
       } else {
           if (!options.types[2].writable) {
               html += "<li>The directory you identified is not writable.</li>";
           }              
           if (!options.types[2].exists) {
               html += "<li>The path you specified does not exist. (TODO - fix me)</li>";
           }              
       }
       if (!options.types[2].htaccess_ok) {
           html += "<li>The document root you specified is not capable of serving CGI applications.</li>";
           resolve += "<li>You will need to modify your web server's configuration by adding the following:<br><code><pre>";
	   //TODO - make this web server specific based upon CGI->server_software
           resolve += "&lt;Directory "+docroot_path+"&gt;\n";
           resolve += "  Options +ExecCGI\n";
           resolve += "  AllowOverride All\n";
           resolve += "  AddHandler cgi-handler .cgi\n";
           resolve += "&lt;/Directory&gt;</pre></code></li>";
       }              
       html += "</ul><h4>How to resolve the problem</h4><ul>";
       html += resolve;
       html += "</ul>";
   } else if (link.hasClass('install-3')) {
       html = '';
   }
   return html;
}
function check_prereqs() {
  pages.unshift( $('#upgrade').html() );
  $('#upgrade').html('<img src="http://localhost/~breese/mt/mt-static/images/indicator.gif" />');
  $.post('mt-install.cgi', 
         { 
           'json'    : 'check_prereqs',
           'cgibin'  : cgibin_path,
           'docroot' : docroot_path 
         },
         function(data){
           $('#back').attr('disabled',false);
           $('#upgrade').html(data.html);
           $('#tryagain-prereq').click(function(){
             if (open_drawer_is != 0) { close_drawer(); }
             check_prereqs();
           });
           $('.fixme').click(function(){ 
             var html = init_cpan_help( $(this), $(this).attr('title') );
             toggle_drawer($(this).attr('title'),html); 
           });
         },
         "json");
}
function begin() {
  pages.unshift( $('#upgrade').html() );
  $('#upgrade').html('<img src="http://localhost/~breese/mt/mt-static/images/indicator.gif" />');
  $.post('mt-install.cgi', 
         { 
           'json'    : 'find_installs',
           'cgibin'  : cgibin_path,
           'docroot' : docroot_path 
         },
         function(data){
           $('#back').attr('disabled',false);
           $('#upgrade').html(data.html);
           $('li.impossible input').attr('disabled',true);
           $('.fixme').click(function(){ 
             var html = init_setup_help( $(this), data.options );
             toggle_drawer($(this).attr('id'),html); 
           });
           $('#next-checkprereq').click(function(){
               install_type = $('ul.install_opt input[@checked=true]').val();
               alert('install type: ' + install_type);
	       check_prereqs();
           });
         },
         "json");
}

    </script>
};
    $html .= <<EOH;
    <style>
body {
  font-family: Georgia;
  }
#container{
  margin: 50px auto 0;
  text-align: left;
  width:360px;
  position: relative;
  }
#container-inner{
  border: 1px solid #cfdde5;
  background-image: url('http://localhost/~breese/mt/mt-static/images/chromeless/chromeless_bg_b.png');
  background-repeat: repeat-x;
  background-position: bottom center; 
  background-color: white;
  z-index: 1;
min-height: 360px;
  }
#drawer { 
  position: absolute;
  top: 10px;
  border: 1px solid #CFDDEF; 
  width: 293px; 
  height: 318px; 
  padding: 15px;
  background: white;
  z-index: -1;
 display:none;
  }
#drawer a {
  position: absolute;
  display: block;
  top: 10px;
  right: 10px;
  }
#drawer h4 { font-weight: bold; margin-bottom: 8px; }
#drawer-title {
  font-size: 1.3em;
  font-weight: bold;
  margin-bottom: 10px;
  }
#container #drawer li {
  list-style: square;
}
#drawer ul {
  margin-left: 20px;
  }
#drawer-content {
  font-size: 1.1em;
  }
#upgrade img { text-align: center; }

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
#container li {
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

#nav .step{background:url('http://localhost/~breese/mt/mt-static/images/chromeless/nav_off.png');}
#nav .step_active{background:url('http://localhost/~breese/mt/mt-static/images/chromeless/nav_on.png');}


/* Begin Simple CSS */
/* Movable Type (r) (C) 2001-2009 Six Apart, Ltd. All Rights Reserved
 * This file is combined from multiple sources.  
 * Consult the source files for their
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
.zero-state a.close-me{display:none;}
.debug-panel{width:100%;border-top:1px dotted #f55;margin-top:5px;background-color:#daa;text-align:left;}
.debug-panel h3{padding:5px;font-size:12px;margin:0;background-color:#f55;color:#fff;}
.debug-panel-inner li{white-space:pre;}
.debug-panel-inner li:hover{background-color:#eaa;}
.debug-panel-inner{padding:5px;font-family:'Andale Mono', monospace;font-size:10px;max-height:200px;overflow:auto;}
body{font-family:"Helvetica Neue", Helvetica, Arial, sans-serif;font-size:12px;background-color:#fff;}
h1, h2, p, ul{margin-bottom:12px;}
h2{font-weight:bold;font-size:14px;}
strong{font-weight:bold;}
em{font-style:italic;}
a:link,a:visited{color:#33789c;}
a:hover,a:active{color:#a2ad00;}
.ready{font-weight:bold;color:#93b06b;}
.note{clear:both;padding:10px 0 10px 0;}
#page-title{font-size:24px;font-weight:normal;margin-top:10px;}
p.intro{font-size:14px;font-weight:normal;}
.hint{line-height:1.1;font-size:11px;padding-top:2px;}
#db_hint{margin-top:-10px;margin-bottom:10px;}
#db_hint p{margin-bottom:3px;}
#error_more{margin:10px 0 15px;font-weight:normal;overflow:auto;padding:5px 0 10px 0;}
#continue{margin-bottom:20px;}
.module-name{font-weight:bold;}
.module-name a{color:black;text-decoration:none;}
.module-name a:hover{text-decoration:underline;}
#brand{position:relative;margin:30px 0 0 20px;height:34px;width:192px;font-size:32px;font-family:Helvetica;font-weight: bold;}
#content #content-inner{margin:0 18px;}
#nav{float:right;margin-right:20px;}
#nav .step{float:left;height:15px;width:14px;}
#nav .step_active{float:left;height:15px;width:14px;}
.edit-entry .actions-bar-top,.edit-entry .actions-bar-bottom{display:none;}
#container.show-actions-bar-top .actions-bar-top{display:block;}
#container.show-actions-bar-bottom .actions-bar-bottom{display:block;}
ul li{list-style-type:disc;margin-left:15px;}
fieldset{margin:0;}
.field{border:0;mat-weight:bold;margin-boctions-bar .plugin-actions button{width:auto;overflow:visible;}
.buttons a:hover,.buttons a:active,.buttons button:hover,
.listing .actions-bar .actions a:hover,
.listing .actions-bar .actions a:active,
.listing .actions-bar .actions button:hover,
.actions-bar .plugin-actions a:hover,
.actions-bar .plugin-actions a:active,
.actions-bar .plugin-actions button:hover{color:#33789c !important;background-position:50% 30%;}
.system .buttons a:hover,
.system .buttons a:active,
.system .buttons button:hover,
.system .listing .actions-bar .actions a:hover,
.system .listing .actions-bar .actions a:active,
.system .listing .actions-bar .actions button:hover,
.system .actions-bar .plugin-actions a:hover,
.system .actions-bar .plugin-actions a:active,
.system .actions-bar .plugin-actions button:hover{color:#7f8833 !important;}
.dialog .actions-bar{margin-bottom:10px;}
.dialog .actions-bar-login .actions a,
.dialog .actions-bar-login .actions button,
.dialog .actions-bar-login .actions select{float:left;margin:0 5px 0 0;}
.upgrade .upgrade-process{overflow:auto;margin:10px 0;border:1px solid #ccc;padding:10px;background-color:#fafafa;height:200px;}
.mt-config-file-path{overflow:auto;overflow-x:auto;overflow-y:hidden;height:2.75em;font-weight:bold;}
ul#profile-data li{margin-left:0;padding-left:0;list-style:none;}
#profile_userpic-field .field-content label{display:block;margin-top:5px;}
.mt-profile-edit form{margin-bottom:.75em;}
.custom-field-radio-list{margin-bottom:.25em;}
.custom-field-radio-list li{list-style:none;margin-left:0;}
.pkg:after{content:" ";display:block;visibility:hidden;clear:both;height:0.1px;font-size:0.1em;line-height:0;}
.pkg{display:inline-block;}/*\*/* html .pkg{height:1%;}.pkg[class]{height:auto;}.pkg{display:block;}/**/.hidden{display:none !important;}.visible{display:block;}.invisible{display:block !important;visibility:hidden !important;position:absolute !important;left:0 !important;top:0 !important;width:0 !important;height:0 !important;font-size:0.1px !important;line-height:0 !important;}.overflow-auto{overflow:auto;}.overflow-hidden{overflow:hidden;}.right{float:right;}.left{float:left;display:inline;}.center{margin-left:auto;margin-right:auto;}.inline{display:inline;}.nowrap{white-space:nowrap;}
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
<body class="chromeless dialog">
<div id="container">
<div id="drawer">
  <div id="drawer-inner">
    <a class="close" href="#">close</a>
    <h3 id="drawer-title">Need some help?</h3>
    <div id="drawer-content">
    <p>It appears something went wrong.</p>
    </div>
  </div>
</div>

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
                <div id="upgrade">
EOH
    print $html;
}

sub print_footer {
    print qq{
                </div>
                <button id="back">Back</button>
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

</div><!--container-->
</body>
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

package JSON::Converter;
use Carp;
$JSON::Converter::VERSION = 0.995;
sub new {
    my $class = shift;
    bless {indent => 2, pretty => 0, delimiter => 2, @_}, $class;
}
sub objToJson {
	my $self = shift;
	my $obj  = shift;
	my $opt  = shift;

	local(@{$self}{qw/autoconv execcoderef skipinvalid/});
	local(@{$self}{qw/pretty indent delimiter/});

	$self->_initConvert($opt);

	return $self->toJson($obj);
}
sub toJson {
	my ($self, $obj) = @_;

	if(ref($obj) eq 'HASH'){
		return $self->hashToJson($obj);
	}
	elsif(ref($obj) eq 'ARRAY'){
		return $self->arrayToJson($obj);
	}
	else{
		return;
	}
}
sub hashToJson {
	my $self = shift;
	my $obj  = shift;
	my ($k,$v);
	my %res;

	my ($pre,$post) = $self->_upIndent() if($self->{pretty});

	if(grep { $_ == $obj } @{ $self->{_stack_myself} }){
		die "circle ref!";
	}

	push @{ $self->{_stack_myself} },$obj;

	for my $k (keys %$obj){
		my $v = $obj->{$k};
		if(ref($v) eq "HASH"){
			$res{$k} = $self->hashToJson($v);
		}
		elsif(ref($v) eq "ARRAY"){
			$res{$k} = $self->arrayToJson($v);
		}
		else{
			$res{$k} = $self->valueToJson($v);
		}
	}

	pop @{ $self->{_stack_myself} };

	$self->_downIndent() if($self->{pretty});

	if($self->{pretty}){
		my $del = $self->{_delstr};
		return "{$pre"
		 . join(",$pre", map { _stringfy($_) . $del .$res{$_} } keys %res)
		 . "$post}";
	}
	else{
		return '{'. join(',',map { _stringfy($_) .':' .$res{$_} } keys %res) .'}';
	}

}


sub arrayToJson {
	my $self = shift;
	my $obj  = shift;
	my @res;

	my ($pre,$post) = $self->_upIndent() if($self->{pretty});

	if(grep { $_ == $obj } @{ $self->{_stack_myself} }){
		die "circle ref!";
	}

	push @{ $self->{_stack_myself} },$obj;

	for my $v (@$obj){
		if(ref($v) eq "HASH"){
			push @res,$self->hashToJson($v);
		}
		elsif(ref($v) eq "ARRAY"){
			push @res,$self->arrayToJson($v);
		}
		else{
			push @res,$self->valueToJson($v);
		}
	}

	pop @{ $self->{_stack_myself} };

	$self->_downIndent() if($self->{pretty});

	if($self->{pretty}){
		return "[$pre" . join(",$pre" ,@res) . "$post]";
	}
	else{
		return '[' . join(',' ,@res) . ']';
	}
}


sub valueToJson {
	my $self  = shift;
	my $value = shift;

	return 'null' if(!defined $value);

	if($self->{autoconv} and !ref($value)){
		return $value  if($value =~ /^-?(?:0|[1-9][\d]*)(?:\.[\d]+)?$/);
		return 'true'  if($value =~ /^true$/i);
		return 'false' if($value =~ /^false$/i);
	}

	if(! ref($value) ){
		return _stringfy($value)
	}
	elsif($self->{execcoderef} and ref($value) eq 'CODE'){
		my $ret = $value->();
		return 'null' if(!defined $ret);
		return $self->toJson($ret) if(ref($ret));
		return _stringfy($ret);
	}
	elsif( ! UNIVERSAL::isa($value, 'JSON::NotString') ){
		die "Invalid value" unless($self->{skipinvalid});
		return 'null';
	}

	return defined $value->{value} ? $value->{value} : 'null';
}


sub _stringfy {
	my $arg = shift;
	my $l   = length $arg;
	my $s   = '"';
	my $i = 0;

	while($i < $l){
		my $c = substr($arg,$i++,1);
		if($c ge ' '){
			$c =~ s{(["\\])}{\\$1};
			$s .= $c;
		}
		elsif($c =~ tr/\n\r\t\f\b/nrtfb/){
			$s .= '\\' . $c;
		}
		else{
			$s .= '\\u00' . unpack('H2',$c);
		}
	}

	return $s . '"';
}
sub _initConvert {
	my $self = shift;
	my %opt  = %{ $_[0] } if(@_ > 0 and ref($_[0]) eq 'HASH');

	$self->{autoconv}    = $JSON::AUTOCONVERT if(!defined $self->{autoconv});
	$self->{execcoderef} = $JSON::ExecCoderef if(!defined $self->{execcoderef});
	$self->{skipinvalid} = $JSON::SkipInvalid if(!defined $self->{skipinvalid});

	$self->{pretty}      =  $JSON::Pretty    if(!defined $self->{pretty});
	$self->{indent}      =  $JSON::Indent    if(!defined $self->{indent});
	$self->{delimiter}   =  $JSON::Delimiter if(!defined $self->{delimiter});

	for my $name (qw/autoconv execcoderef skipinvalid pretty indent delimiter/){
		$self->{$name} = $opt{$name} if(defined $opt{$name});
	}

	$self->{_stack_myself} = [];
	$self->{indent_count}  = 0;

	$self->{_delstr} = 
		$self->{delimiter} ? ($self->{delimiter} == 1 ? ': ' : ' : ') : ':';

	$self;
}


sub _upIndent {
	my $self  = shift;
	my $space = ' ' x $self->{indent};
	my ($pre,$post) = ('','');

	$post = "\n" . $space x $self->{indent_count};

	$self->{indent_count}++;

	$pre = "\n" . $space x $self->{indent_count};

	return ($pre,$post);
}


sub _downIndent { $_[0]->{indent_count}--; }

package JSON;

use strict;
use base qw(Exporter);

@JSON::EXPORT = qw(objToJson);

use vars qw($AUTOCONVERT $VERSION
            $ExecCoderef $SkipInvalid $Pretty $Indent $Delimiter);

$VERSION     = 0.99;

$AUTOCONVERT = 1;
$ExecCoderef = 0;
$SkipInvalid = 0;
$Indent      = 2; # (pretty-print)
$Delimiter   = 2; # (pretty-print)  0 => ':', 1 => ': ', 2 => ' : '

my $parser; # JSON => Perl
my $conv;   # Perl => JSON

sub new {
	my $class = shift;
	my %opt   = @_;
	bless {
		conv   => undef,  # JSON::Converter [perl => json]
		parser => undef,  # JSON::Parser    [json => perl]
		# below fields are for JSON::Converter
		autoconv    => 1,
		skipinvalid => 0,
		execcoderef => 0,
		pretty      => 0, # pretty-print mode switch
		indent      => 2, # for pretty-print
		delimiter   => 2, # for pretty-print
		# overwrite
		%opt,
	}, $class;
}

sub objToJson {
	my $self = shift || return;
	my $obj  = shift;

	if(ref($self) !~ /JSON/){ # class method
		my $opt = __PACKAGE__->_getDefaultParms($obj);
		$obj  = $self;
		$conv ||= JSON::Converter->new();
		$conv->objToJson($obj, $opt);
	}
	else{ # instance method
		my $opt = $self->_getDefaultParms($_[0]);
		$self->{conv}
		 ||= JSON::Converter->new( %$opt );
		$self->{conv}->objToJson($obj, $opt);
	}
}

sub _getDefaultParms {
	my $self = shift;
	my $opt  = shift;
	my $params;

	if(ref($self)){ # instance
		my @names = qw(pretty indent delimiter autoconv);
		my ($pretty, $indent, $delimiter, $autoconv) = @{$self}{ @names };
		$params = {
			pretty => $pretty, indent => $indent,
			delimiter => $delimiter, autoconv => $autoconv,
		};
	}
	else{ # class
		$params = {pretty => $Pretty, indent => $Indent, delimiter => $Delimiter};
	}

	if($opt and ref($opt) eq 'HASH'){ %$params = ( %$opt ); }

	return $params;
}

sub autoconv { $_[0]->{autoconv} = $_[1] if(defined $_[1]); $_[0]->{autoconv} }
sub pretty { $_[0]->{pretty} = $_[1] if(defined $_[1]); $_[0]->{pretty} }
sub indent { $_[0]->{indent} = $_[1] if(defined $_[1]); $_[0]->{indent} }
sub delimiter { $_[0]->{delimiter} = $_[1] if(defined $_[1]); $_[0]->{delimiter} }

sub Number {
	my $num = shift;
	if(!defined $num or $num !~ /^-?(0|[1-9][\d]*)(\.[\d]+)?$/){
		return undef;
	}
	bless {value => $num}, 'JSON::NotString';
}

sub True {
	bless {value => 'true'}, 'JSON::NotString';
}

sub False {
	bless {value => 'false'}, 'JSON::NotString';
}

sub Null {
	bless {value => undef}, 'JSON::NotString';
}

}
